#! /usr/bin/env python
"""Walk-around viewer for a single glTF/GLB model (``oglc-gltf``).

Loads a local ``.gltf``/``.glb`` **or an http(s) URL**, renders it with the
metallic/roughness PBR pass, and lets you walk through the scene with the
keyboard/mouse. If the file contains no lights, a default sun + fill rig is added
so the model is never rendered in the dark. Shadows are on by default.

Each camera the glTF defines becomes a ``Viewpoint`` node in the scene, so PageUp/
PageDown cycle between them through OpenGLContext's standard viewpoint mechanism
(the same one VRML97 worlds use); cameras are referred to by name where they have
one. ``--capture`` renders the scene to a PNG and exits, after a short settle delay
so the analytic-sky IBL has converged.

Usage::

    oglc-gltf path/to/model.glb
    oglc-gltf https://example.com/model.glb
    oglc-gltf model.glb --camera aerial --capture shot.png --capture-delay 0.5
    oglc-gltf model.glb --list-cameras
    GLTF=path/to/model.gltf oglc-gltf

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
                            named for the program: oglc-gltf-screen-0001.png,
                            also in the current directory
    Alt + f                 the developer overlay: frame rate and time, which
                            renderer features are on, what the last frame cost
                            in shapes and draw calls, and where the camera is
                            (see docs/hud.html)

In walk mode (default) gravity + collision keep you on the ground and out of
walls; press ``g`` to drop to the free-fly camera if an initial viewpoint leaves
you stuck inside the model, and ``g`` again to resume walking from there.
"""
import argparse
import os
import sys
import threading
from math import pi, sin, asin, atan2
from typing import TYPE_CHECKING, Any, Callable, Optional, cast

os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')
os.environ.setdefault('OPENGLCONTEXT_SHADOWS', '1')
# The directional-shadow cascade count is left fps-adaptive for interactive use:
# each extra cascade is a full depth pass over the whole scene (the dominant
# shadow-pass cost), so the controller sheds cascades when the frame rate sags.
# It is pinned only for --capture (see apply_render_env), where a reproducible
# frame matters more than the frame rate.
# Keep the warm analytic sky, but at reduced strength so the sun's cast shadows
# read clearly instead of being washed out by full-strength ambient.
os.environ.setdefault('OPENGLCONTEXT_IBL_INTENSITY', '0.4')

from OpenGLContext import testingcontext
from OpenGLContext.scenegraph.scenegraph import SceneGraph as sceneGraph
from OpenGLContext.scenegraph.transform import Transform
from OpenGLContext.scenegraph.light import Light, DirectionalLight, PointLight
from OpenGLContext.scenegraph.background import Background
from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import look_orientation
from OpenGLContext.capture import SettleCapture

if TYPE_CHECKING:
    from OpenGLContext.context import Context as BaseContext
    from OpenGLContext.loaders.gltf.scene import GLTFScene
else:
    BaseContext = testingcontext.getInteractive()

# look_orientation used to live here as ``_orientation``; kept as an alias so any
# external caller importing it keeps working.
_orientation = look_orientation


#: Movement speeds a viewer offers, in scene units per second at scale 1.
WALK_SPEED = 3.0
RUN_SPEED = 6.0
FLY_SPEED = 8.0

#: Radians per second a turn starts at, and the multiple a held turn ramps up
#: to: a viewer needs both a precise nudge and a quick spin in close quarters.
TURN_RATE = 0.9
TURN_ACCELERATION = 3.0


def movement_modes(scale: float = 1.0):
    """The ways of moving this viewer offers, as declared nodes.

    Declared rather than hand-rolled: one settings screen can present the
    navigation of every viewer, and a game embedding this one retunes it by
    setting fields rather than subclassing.

    ``scale`` sizes the speeds to the thing being viewed — a viewer frames
    models from a bolt to a city, and a speed that suits one is useless for the
    other, so it is a parameter rather than a constant.
    """
    from OpenGLContext.move import modes as _modes
    return [
        _modes.WalkMode(name='walk', walkSpeed=WALK_SPEED * scale,
                        runSpeed=RUN_SPEED * scale,
                        turnRate=TURN_RATE, turnAcceleration=TURN_ACCELERATION),
        _modes.FlyMode(name='fly', flySpeed=FLY_SPEED * scale,
                       turnRate=TURN_RATE, turnAcceleration=TURN_ACCELERATION),
    ]


def _is_url(src: object) -> bool:
    """True if ``src`` is an http(s) URL rather than a local filesystem path."""
    return isinstance(src, str) and (
        src.startswith('http://') or src.startswith('https://'))


def _resolve_source(src: str | None) -> str | None:
    """Validate a CLI/env source. A local path must exist; an http(s) URL is
    returned unchanged so the loader fetches it and resolves its external
    resources against the document origin (see :func:`_load_source`)."""
    if src is None:
        return None
    if _is_url(src):
        return src
    if not os.path.exists(src):
        raise SystemExit("ERROR: file not found: %s" % src)
    return src


def _load_source(src: str) -> "GLTFScene":
    """Load a :class:`GLTFScene` from a local path or an http(s) URL.

    A URL goes through :func:`gltf.load_gltf_url`, which fetches the document over
    the security-hardened resolver (same-origin, size-capped, disk-cached) and
    resolves a multi-file ``.gltf``'s external ``.bin``/image references relative
    to the document URL. A single-file downloader could not: it lost the base URL,
    so those relative references had nowhere to resolve from. A self-contained
    ``.glb`` loads correctly either way.
    """
    if _is_url(src):
        return gltf.load_gltf_url(src)
    return gltf.load_gltf(src)


def _count_lights(node: Any, seen: set[int] | None = None) -> int:
    """Recursively count Light nodes reachable through ``children`` fields."""
    if seen is None:
        seen = set()
    if id(node) in seen:
        return 0
    seen.add(id(node))
    total = 1 if isinstance(node, Light) else 0
    for child in getattr(node, 'children', None) or ():
        total += _count_lights(child, seen)
    return total


# -- command line ---------------------------------------------------------

def _parse_size(text: str) -> tuple[int, int]:
    """Parse a ``WxH`` window size into an (int, int) tuple."""
    try:
        w, h = (int(v) for v in text.lower().split('x'))
        return (w, h)
    except Exception:
        raise argparse.ArgumentTypeError("size must be WxH, e.g. 1100x680") from None


def build_parser(prog: str = 'oglc-gltf') -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description='Walk-around viewer for a single glTF/GLB model.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="A local path or an http(s) URL. .glb is self-contained (URLs work "
               "cleanly); a .gltf that references external .bin/textures should be "
               "downloaded locally as a set. Falls back to the GLTF env var.",
    )
    parser.add_argument('source', nargs='?', default=None,
                        help='glTF/GLB file path or http(s) URL (or set GLTF=...)')
    parser.add_argument('--camera', default=None, metavar='NAME|INDEX',
                        help='initial camera, by glTF name (preferred) or 0-based index')
    parser.add_argument('--list-cameras', action='store_true',
                        help='print the glTF camera names and exit')
    parser.add_argument('--no-cameras', action='store_true',
                        help='ignore embedded glTF cameras; centre and auto-frame the model')
    parser.add_argument('--capture', metavar='PATH', default=None,
                        help='render to PATH (PNG) after settling, then exit')
    parser.add_argument('--capture-delay', type=float, default=0.5, metavar='SECONDS',
                        help='seconds to let the scene settle before --capture (default 0.5)')
    parser.add_argument('--frames', type=int, default=10, metavar='N',
                        help='minimum frames to render before --capture (default 10)')
    parser.add_argument('--shadows', action=argparse.BooleanOptionalAction, default=None,
                        help='force shadows on/off (default: on)')
    parser.add_argument('--lights', choices=['auto', 'on', 'off'], default='auto',
                        help="default light rig: auto (add only if the file has none), "
                             "on (always add), off (never add)")
    parser.add_argument('--ibl-intensity', type=float, default=None, metavar='SCALE',
                        help='scale the analytic-sky ambient/IBL contribution')
    parser.add_argument('--environment', default=None, metavar='PREFIX|HDR|NAME',
                        help='image-based environment: a cubemap face prefix '
                             '(<PREFIX>{RT,LF,UP,DN,FR,BK}.jpg), an equirectangular '
                             'Radiance .hdr panorama (local path or http(s) URL), or a '
                             'bundled CC0 HDRI name (e.g. studio_small_03). Reflected '
                             'by metals and drawn as the skybox. Pins full IBL.')
    parser.add_argument('--background', default=None, metavar='SPEC',
                        help="background: 'sky' (default), 'none', or 'R,G,B'")
    parser.add_argument('--size', type=_parse_size, default=None, metavar='WxH',
                        help='window size, e.g. 1100x680')
    parser.add_argument('--physics', action=argparse.BooleanOptionalAction,
                        default=(os.environ.get('OPENGLCONTEXT_PHYSICS', '0') != '0'),
                        help='walk the model with gravity + collision (default off, so '
                             'an isolated/floorless model stays framed instead of the '
                             'avatar falling past it); press "g" or pass --physics to walk')
    parser.add_argument('--turntable', action='store_true',
                        help='slowly rotate the model')
    parser.add_argument('--no-rotate', dest='no_rotate', action='store_true',
                        help='never rotate the model (fixed orientation, to line a '
                             'capture up with a reference image)')
    parser.add_argument('--animation', default=None, metavar='NAME|INDEX',
                        help='play this glTF animation (name or 0-based index); '
                             'default: play the first animation if any')
    parser.add_argument('--no-animation', dest='animate', action='store_false',
                        default=True, help='do not play embedded animations')
    parser.add_argument('--anim-time', type=float, default=None, metavar='SECONDS',
                        help='pin the animation to this time (deterministic capture)')
    parser.add_argument('--yaw', type=float, default=float(os.environ.get('YAW', -0.62)),
                        help='initial model yaw (radians) when auto-framing')
    parser.add_argument('--margin', type=float, default=None, metavar='FACTOR',
                        help='auto-frame fit factor (default 1.15); below 1 pulls '
                             'the camera in so the model fills more of the frame')
    parser.add_argument('--elevation', type=float, default=None, metavar='FRAC',
                        help='auto-frame camera height as a fraction of the model '
                             'radius (default 0.22)')
    parser.add_argument('--tilt', type=float, default=None, metavar='RADIANS',
                        help='auto-frame downward camera tilt in radians (default 0.10)')
    parser.add_argument('--eye', type=_parse_vec3, default=None, metavar='X,Y,Z',
                        help='explicit camera position (world space); with --look-at '
                             'this bypasses auto-framing (e.g. an interior shot)')
    parser.add_argument('--look-at', dest='look_at', type=_parse_vec3, default=None,
                        metavar='X,Y,Z', help='explicit camera target (world space)')
    return parser


def _parse_vec3(text: str) -> tuple[float, ...]:
    parts = text.split(',')
    if len(parts) != 3:
        raise argparse.ArgumentTypeError('expected X,Y,Z, got %r' % text)
    return tuple(float(v) for v in parts)


def parse_args(argv: list[str] | None = None,
               prog: str = 'oglc-gltf') -> argparse.Namespace:
    """Parse viewer command-line arguments into a Namespace (pure, no GL)."""
    return build_parser(prog).parse_args(argv)


def _is_hdr_environment(spec: str | None) -> bool:
    """Whether ``--environment SPEC`` names a Radiance ``.hdr`` panorama.

    An equirectangular ``.hdr``/``.pic`` (local path or http(s) URL) is treated as
    an HDR IBL source + skybox; anything else is a six-face cubemap prefix. The
    query string of a URL is ignored so a CDN link with parameters still matches.
    """
    if not spec:
        return False
    path = spec.split('?', 1)[0].split('#', 1)[0]
    return path.lower().endswith(('.hdr', '.pic'))


def apply_render_env(args: argparse.Namespace) -> None:
    """Translate render-affecting flags into the env vars the renderer reads."""
    if args.shadows is not None:
        os.environ['OPENGLCONTEXT_SHADOWS'] = '1' if args.shadows else '0'
    if args.ibl_intensity is not None:
        os.environ['OPENGLCONTEXT_IBL_INTENSITY'] = str(args.ibl_intensity)
    if getattr(args, 'environment', None):
        from OpenGLContext.loaders import hdri
        try:
            args.environment = hdri.resolve(args.environment)   # catalogue name -> URL
        except KeyError:
            pass    # not a catalogue name; treat as a cubemap prefix / path
        if _is_hdr_environment(args.environment):
            # An equirectangular Radiance .hdr (local path or URL): drives the IBL
            # probe and the HDR skybox. The probe loads it via OPENGLCONTEXT_ENV_HDR.
            os.environ['OPENGLCONTEXT_ENV_HDR'] = args.environment
        else:
            os.environ['OPENGLCONTEXT_ENV_CUBEMAP'] = args.environment
        os.environ.setdefault('OPENGLCONTEXT_IBL', 'full')   # env probe needs full IBL
    elif (getattr(args, 'background', None) == 'none'
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


class TestContext(BaseContext):

    # Config Namespace (from parse_args); main() sets it. A bare __main__/subclass
    # run without one falls back to defaults.
    config: Any = None
    # Source (local path or URL); main() may set this directly for back-compat.
    _gltf_source: str | None = None
    # Members supplied by the interactive runtime base (event + navigation mixins)
    # that the minimal type-check-time ``Context`` alias does not expose.
    platform: Any
    movementManager: Any
    addEventHandler: Any
    # The scenegraph root: the runtime base stores/reads it dynamically
    # (``getSceneGraph`` is a ``getattr``), so type it here for the subclass.
    sg: Any

    def OnInit(self) -> None:  # pragma: no cover - live GL context setup + async kickoff
        if self.config is None:
            self.config = parse_args([])
        self._settle: Optional[SettleCapture] = None
        self._start: float | None = None
        self.model_xform: Optional[Transform] = None
        self.viewpoints: list[Any] = []
        self.cam_index = 0
        self._camera_names: list[str] = []
        self.overlay_text = ''
        self.overlay_error = False
        from time import time
        self._start = time()
        self._physics: Any = None
        self._physics_on = False
        self._free_manager: Any = None
        self._player: Any = None
        self._animations: list[Any] = []
        self._anim_index = 0
        self._anim_names: list[str] = []
        self._anim_playing: bool = getattr(self.config, 'animate', True)
        self._anim_clock = 0.0
        self._anim_last: float | None = None
        self._default_model_rotation: tuple[float, ...] = (0, 1, 0, 0.0)
        # Async scene loading: the download/decode runs off the render thread and the
        # result is handed back here (via OnIdle) to build the scenegraph and upload to
        # the card. State guarding that handoff:
        self._load_lock = threading.Lock()
        # (scene|None, error|None) awaiting render-thread apply
        self._pending: Optional[tuple[Any, Any]] = None
        self._load_token = 0        # bumped per request; a superseded worker's result is dropped
        self._loading = False       # a background load is in flight
        self._scene_loaded = False  # a real scene has been applied (vs the empty placeholder)
        self._screenshot_pending = False
        self._prepare_source()
        if self.config.capture:
            # A capture must be deterministic: the settle/exit logic has to see the
            # model, so load synchronously before the loop starts.
            from time import perf_counter as _pc
            _t0 = _pc()
            scene = self._load_scene()
            self._load_seconds = round(_pc() - _t0, 3)
            if scene is not None:
                self._build_scenegraph(scene)
                self._scene_loaded = True
            elif getattr(self, 'sg', None) is None:
                # a subclass browsing a catalogue may fail to load one model; keep an
                # empty scene so its error overlay is visible instead of crashing
                self.sg = sceneGraph(children=[])
            self._install_capture()
            self._setup_physics()
        else:
            # Interactive: show an empty scene immediately (with a "Loading ..."
            # overlay) and pull the model in a background thread, so the window never
            # freezes on the download.
            self.sg = sceneGraph(children=[])
            self._install_capture()
            self._setup_physics()
            self._request_initial_scene()

    # -- source + scene loading (overridable seams) -----------------------
    def _prepare_source(self) -> None:
        """Resolve ``self.source`` from config/env. Subclasses may source scenes
        elsewhere (e.g. a downloaded sample catalogue) and skip this."""
        src = self._gltf_source or self.config.source or os.environ.get('GLTF')
        self.source = _resolve_source(src)
        if self.source is None:
            sys.stderr.write(__doc__)
            sys.stderr.write("\nERROR: no glTF/GLB file or URL given.\n")
            raise SystemExit(2)

    def _load_scene(self) -> "GLTFScene":
        """Return a GLTFScene for the current source. Subclasses override to load
        from somewhere other than a single file."""
        sys.stdout.write("Loading %s ...\n" % self.source)
        sys.stdout.flush()
        # KHR_animation_pointer plays live through the Player (the viewer pins it to
        # --anim-time for a deterministic capture), so no load-time baking is needed.
        # _prepare_source raises if the source is unresolved, so it is set here.
        return _load_source(cast(str, self.source))

    # -- async scene loading ----------------------------------------------
    # The slow part of showing a model is the download + decode, which only produces
    # plain data (numpy arrays, PIL images -- no GL). We run it on a worker thread and
    # apply the result on the render thread, where the scenegraph is built and the
    # geometry/textures are uploaded to the card. The render loop keeps drawing (a
    # "Loading ..." overlay) throughout, so switching models never freezes the window.
    def _request_initial_scene(self) -> None:
        """Kick off the first async load. Subclasses browsing a catalogue override
        this to pull their first model instead of a single source file."""
        self._request_scene(self._load_scene, self._loading_label())

    def _loading_label(self) -> str:
        return "Loading %s ..." % os.path.basename(self.source or 'scene')

    def _request_scene(self, produce: Callable[[], Any], label: str) -> None:
        """Load a scene off the render thread. ``produce`` is a no-arg callable run in
        a background thread; it downloads/decodes and returns a scene (and must not
        touch GL). Its result is applied on the render thread by
        :meth:`_poll_pending_scene`. ``label`` is shown while the load is in flight."""
        self._load_token += 1
        token = self._load_token
        self._loading = True
        self.overlay_text = label
        self.overlay_error = False
        self.triggerRedraw(1)

        def worker() -> None:
            error = None
            try:
                scene = produce()
            except Exception as err:            # a bad/unreachable model must not kill the thread
                scene, error = None, err
            with self._load_lock:
                if token == self._load_token:   # a newer request supersedes this one; drop it
                    self._pending = (scene, error)
                    self._loading = False
        threading.Thread(target=worker, name='gltf-load', daemon=True).start()

    def _poll_pending_scene(self) -> bool:
        """On the render thread: apply a background-loaded scene if one is ready.

        Building the scenegraph here (not in the worker) keeps every GL upload on the
        render thread. Returns True if a result was applied this tick."""
        with self._load_lock:
            pending = self._pending
            self._pending = None
        if pending is None:
            return False
        scene, error = pending
        if scene is not None:
            self._apply_loaded(scene)
        else:
            self._apply_failed(error)
        self.triggerRedraw(1)
        return True

    def _apply_loaded(self, scene: Any) -> None:
        """Render thread: build the scenegraph for a freshly loaded scene."""
        self._build_scenegraph(scene)
        self._on_scene_ready()

    def _apply_failed(self, error: BaseException | None) -> None:
        """Render thread: a background load raised. Keep a visible error overlay."""
        if getattr(self, 'sg', None) is None:
            self.sg = sceneGraph(children=[])
        self.overlay_error = True
        msg = str(error).splitlines()[0][:60] if error else 'load failed'
        self.overlay_text = "FAILED: %s" % msg
        sys.stderr.write("Load failed: %s\n" % (error,))
        sys.stderr.flush()

    def _on_scene_ready(self) -> None:
        """Render thread, just after a freshly loaded scene's scenegraph is built.
        Establish physics for the new scene (the single-file viewer loads once)."""
        first = not self._scene_loaded
        self._scene_loaded = True
        if self.config.capture:
            return
        if getattr(self.config, 'physics', False):
            self._physics = None              # rebuild the collision world for this scene
            if not self._set_physics(True) and first:
                sys.stdout.write("Physics: no walkable geometry; using free-fly.\n")
                sys.stdout.flush()

    # -- screenshot -------------------------------------------------------
    def _request_screenshot(self, event: Any = None) -> None:
        """Queue a framebuffer grab; taken in SwapBuffers before the swap (reading
        the buffer after the swap returns stale data in the dev-container)."""
        self._screenshot_pending = True
        self.triggerRedraw(1)

    def _save_screenshot(self) -> None:  # pragma: no cover - GL framebuffer read-back
        from datetime import datetime
        from OpenGLContext.capture import capture_to_png
        name = datetime.now().strftime("gltf-%Y-%m-%dT%H-%M-%S.png")
        path = os.path.join(os.getcwd(), name)
        if capture_to_png(path, skip_blank=False):
            sys.stdout.write("Saved screenshot %s\n" % path)
        else:
            sys.stderr.write("Screenshot failed (Pillow missing?).\n")
        sys.stdout.flush()

    # -- scenegraph assembly ----------------------------------------------
    def _build_scenegraph(self, scene: Any) -> None:
        """(Re)build ``self.sg`` from a loaded scene, honouring the config. Safe to
        call again to swap the model (subclasses browsing a catalogue rely on this)."""
        self.radius = scene.radius or 1.0
        radius = self.radius
        # Camera exposure the loader's light meter derived from the scene's own
        # KHR_lights_punctual lights (1.0 for normalized/IBL-lit scenes); the PBR
        # pass reads this off the context each frame. The meter is for *self-lit*
        # scenes rendered on black (background 'none'), where the scene's own bright
        # punctual lights would otherwise clip. When the model is shown against an
        # environment (sky/cube/hdr), that environment is the key light, so the
        # punctual-only meter wrongly crushes the scene to near-black -- e.g. a lamp
        # whose bulb sits at its own centre (d^2 -> 0) meters an absurd illuminance.
        # Only apply the metered stop-down in the black-background self-lit case.
        metered = float(getattr(scene, 'exposure', 1.0))
        self.gltf_exposure = metered if self.config.background == 'none' else 1.0
        # glTF has no ambient term (lighting is IBL + punctual); only used when no
        # environment probe is active (background 'none'). Zero it so self-lit scenes
        # read as dark + crisp lights, not washed by a flat fill. See _flat.py.
        self.gltf_scene_ambient = 0.0
        self._camera_names = [(p.get('name') or 'camera') for p in scene.cameras]
        use_cams = (not self.config.no_cameras) and bool(scene.viewpoints)

        children = []
        bg = self._make_background()
        if bg is not None:
            children.append(bg)

        if use_cams:
            # Baked cameras are authored in the model's own space, so show the model
            # as-is (no re-centring) or the Viewpoint poses won't line up.
            self.model_xform = Transform(children=[scene.group])
            self._default_model_rotation = (0, 1, 0, 0.0)
            children.append(self.model_xform)
            children.extend(scene.viewpoints)
            self.viewpoints = list(scene.viewpoints)
        else:
            cx, cy, cz = scene.center
            centred = Transform(translation=(-cx, -cy, -cz), children=[scene.group])
            self._default_model_rotation = (0, 1, 0, self.config.yaw)
            self.model_xform = Transform(rotation=self._default_model_rotation,
                                         children=[centred])
            children.append(self.model_xform)
            self.viewpoints = []

        children.extend(self._lights_children(scene, radius))
        self.sg = sceneGraph(children=children)
        self._setup_animation(scene)

        if use_cams:
            sys.stdout.write("Found %d camera(s); PageUp/PageDown to cycle.\n"
                             % len(self.viewpoints))
            self._select_initial_camera()
        else:
            self._frame(radius)
        self._update_overlay()

    # -- animation --------------------------------------------------------
    def _setup_animation(self, scene: Any) -> None:
        """Bind a Player to the chosen animation of the freshly loaded scene."""
        self._animations = list(getattr(scene, 'animations', []) or [])
        self._anim_names = [a.name or ('animation%d' % i)
                            for i, a in enumerate(self._animations)]
        self._anim_index = self._resolve_animation(getattr(self.config, 'animation', None))
        self._anim_clock = 0.0
        self._anim_last = None
        self._player = None
        # A pinned --anim-time captures one deterministic pose, so it must clamp
        # (not loop): t == duration should show the END pose, not wrap to t=0.
        loop = getattr(self.config, 'anim_time', None) is None
        if self._animations and getattr(self.config, 'animate', True):
            self._player = scene.player(self._anim_index, loop=loop)
            if self._player is not None:
                sys.stdout.write("Playing animation [%d/%d] %r (%.2fs).\n" % (
                    self._anim_index + 1, len(self._animations),
                    self._anim_names[self._anim_index], self._player.duration))
                sys.stdout.flush()
                # Show the first pose immediately (before the first idle tick).
                self._player.evaluate(self._pinned_or(0.0))

    def _resolve_animation(self, sel: Any) -> int:
        """Index of the animation named/numbered ``sel`` (default 0)."""
        if not self._animations:
            return 0
        if sel is None:
            return 0
        for i, name in enumerate(self._anim_names):
            if name == sel or name.lower() == str(sel).lower():
                return i
        if str(sel).lstrip('-').isdigit():
            return int(sel) % len(self._animations)
        sys.stderr.write("No animation matching %r; playing the first.\n" % sel)
        return 0

    def _pinned_or(self, t: float) -> float:
        at = getattr(self.config, 'anim_time', None)
        return at if at is not None else t

    def _advance_animation(self) -> bool:
        """Advance the animation clock by wall time and evaluate. Returns True if
        a redraw is needed."""
        if self._player is None:
            return False
        if getattr(self.config, 'anim_time', None) is not None:
            self._player.evaluate(self.config.anim_time)
            return False        # a pinned pose is static; no continuous redraw
        if not self._anim_playing:
            return False
        now = self._now()
        if self._anim_last is not None:
            self._anim_clock += min(now - self._anim_last, 0.1)
        self._anim_last = now
        self._player.evaluate(self._anim_clock)
        return True

    def _toggle_animation(self, event: Any = None) -> None:
        self._anim_playing = not self._anim_playing
        self._anim_last = None      # avoid a jump from paused wall-time
        self._update_overlay()
        self.triggerRedraw(1)

    def _cycle_animation(self, delta: int) -> None:
        if not self._animations:
            return
        self._anim_index = (self._anim_index + delta) % len(self._animations)
        # Rebind a fresh Player for the new index against the same node map.
        from OpenGLContext.loaders.gltf.animation import Player
        self._player = Player(self._animations[self._anim_index],
                              self._player.node_transforms if self._player else {},
                              node_morph=self._player.node_morph if self._player else {},
                              loop=True)
        self._anim_clock = 0.0
        self._anim_last = None
        self._update_overlay()
        self.triggerRedraw(1)

    def _next_animation(self, event: Any = None) -> None:
        self._cycle_animation(1)

    def _prev_animation(self, event: Any = None) -> None:
        self._cycle_animation(-1)

    def _toggle_turntable(self, event: Any = None) -> None:
        """Start/stop the slow model spin; stopping snaps back to the default
        (reference-comparable) orientation so a capture matches the reference pose."""
        self.config.turntable = not getattr(self.config, 'turntable', False)
        if self.config.turntable:
            self._start = self._now()          # spin from the current default pose
        elif self.model_xform is not None:
            self.model_xform.rotation = self._default_model_rotation
        self.triggerRedraw(1)

    def _lights_children(self, scene: Any, radius: float) -> list[Any]:
        """Light nodes to add, per ``--lights`` (auto/on/off)."""
        mode = self.config.lights
        if mode == 'off':
            return []
        n_lights = _count_lights(scene.group)
        if mode == 'auto' and n_lights:
            sys.stdout.write("Found %d light(s) in the file; using them.\n" % n_lights)
            sys.stdout.flush()
            return []
        sys.stdout.write("Adding a default sun + fill rig.\n")
        sys.stdout.flush()
        return self._default_lights(radius)

    def _make_background(self) -> Any:
        """Background node from ``--background`` (None -> 'sky').

        A loaded IBL environment cubemap (``OPENGLCONTEXT_ENV_CUBEMAP``) is also
        drawn as the skybox, so the environment reflected by metals is the same one
        visible behind them -- unless ``--background`` names an explicit colour.
        """
        spec = self.config.background
        if spec == 'none':
            return None
        if spec == 'sky':
            return self._sky()
        # 'cube'/'hdr' or unset: draw the loaded environment as the skybox so the
        # sky matches what metals reflect, falling back to the gradient sky.
        if spec in ('cube', 'hdr', None):
            hdr_bg = self._env_hdr_background()
            if hdr_bg is not None:
                return hdr_bg
            cube = self._env_cube_background()
            if cube is not None:
                return cube
            return self._sky()
        try:
            rgb = tuple(float(v) for v in spec.split(','))
            if len(rgb) != 3:
                raise ValueError
        except ValueError:
            sys.stderr.write("bad --background %r; using sky.\n" % spec)
            return self._sky()
        return Background(skyColor=[rgb])

    @staticmethod
    def _env_hdr_background() -> Any:
        """An HDRBackground skybox from ``OPENGLCONTEXT_ENV_HDR``, or None.

        The same Radiance panorama the IBL probe reflects is drawn behind the
        scene, so the visible sky and the environment metals reflect are one image.
        """
        src = os.environ.get('OPENGLCONTEXT_ENV_HDR', '').strip()
        if not src:
            return None
        from OpenGLContext.scenegraph.hdrbackground import HDRBackground
        return HDRBackground(url=[src])

    @staticmethod
    def _env_cube_background() -> Any:
        """A CubeBackground skybox from the IBL env cubemap face set, or None."""
        from OpenGLContext.passes.ibl import environment_cubemap_prefix, _CUBE_FACES, _CUBE_EXTS
        prefix = environment_cubemap_prefix()
        if not prefix:
            return None
        # map the loader's face suffixes to CubeBackground's url fields
        field_for = {'RT': 'rightUrl', 'LF': 'leftUrl', 'UP': 'topUrl',
                     'DN': 'bottomUrl', 'FR': 'frontUrl', 'BK': 'backUrl'}
        urls: dict[str, list[str]] = {}
        for suffix, _ in _CUBE_FACES:
            path = next((prefix + suffix + ext for ext in _CUBE_EXTS
                         if os.path.exists(prefix + suffix + ext)), None)
            if path is None:
                return None
            urls[field_for[suffix]] = [path]
        from OpenGLContext.scenegraph.cubebackground import CubeBackground
        return CubeBackground(**urls)

    # -- camera selection + cycling ---------------------------------------
    def _resolve_camera(self, sel: str) -> int | None:
        """Index of the camera named/numbered ``sel``, or None."""
        for i, name in enumerate(self._camera_names):
            if name == sel:
                return i
        low = sel.lower()
        for i, name in enumerate(self._camera_names):
            if name.lower() == low:
                return i
        if sel.lstrip('-').isdigit():
            i = int(sel)
            if 0 <= i < len(self.viewpoints):
                return i
        return None

    def _select_initial_camera(self) -> None:
        sel = self.config.camera
        if not sel:
            return
        idx = self._resolve_camera(sel)
        if idx is None:
            sys.stderr.write("No camera matching %r; using the first.\n" % sel)
            return
        # Pre-bind the chosen Viewpoint so the standard mechanism adopts it first.
        self.viewpoints[idx].isBound = True
        self.cam_index = idx

    def setupCallbacks(self) -> None:  # pragma: no cover - binds live event handlers
        BaseContext.setupCallbacks(self)
        for key in ('<pagedown>', 'n'):
            self.addEventHandler('keyboard', name=key, function=self._next_cam)
        for key in ('<pageup>', 'p'):
            self.addEventHandler('keyboard', name=key, function=self._prev_cam)
        self.addEventHandler('keyboard', name='k', function=self._toggle_animation)
        self.addEventHandler('keyboard', name=']', function=self._next_animation)
        self.addEventHandler('keyboard', name='[', function=self._prev_animation)
        self.addEventHandler('keyboard', name='t', function=self._toggle_turntable)
        self.addEventHandler('keyboard', name='<F2>', function=self._request_screenshot)

    def _next_cam(self, event: Any = None) -> None:
        self._cycle_viewpoint(1)

    def _prev_cam(self, event: Any = None) -> None:
        self._cycle_viewpoint(-1)

    def _cycle_viewpoint(self, delta: int) -> None:
        if not self.viewpoints:
            return
        sg = self.getSceneGraph()
        current = getattr(sg, 'boundViewpoint', None) if sg else None
        try:
            i = self.viewpoints.index(current)
        except ValueError:
            i = self.cam_index
        nxt = (i + delta) % len(self.viewpoints)
        if current is not None:
            current.isBound = False
        self.viewpoints[nxt].isBound = True
        self.cam_index = nxt
        # In walk mode the avatar owns the camera, so teleport it to the chosen
        # viewpoint; otherwise the physics pose snaps the view straight back.
        if self._physics is not None:
            vp = self.viewpoints[nxt]
            self._physics.yaw = self._yaw_from_viewpoint(vp)
            self._physics.pitch = 0.0
            self._physics.bind_eye(tuple(vp.position))
            # An elevated/aerial camera has no ground under it; float there rather
            # than fall. A ground-level viewpoint keeps walking.
            self._physics.set_fly(not self._physics.character.grounded)
        self._update_overlay()
        self.triggerRedraw(1)

    def _update_overlay(self) -> None:
        cam = ''
        if self.viewpoints:
            name = self._camera_names[self.cam_index] if self.cam_index < len(
                self._camera_names) else 'camera'
            cam = "[%d/%d] %s   (PgUp/PgDn: cameras)\n" % (
                self.cam_index + 1, len(self.viewpoints), name)
        self.overlay_text = "%s\n%s%s%s" % (
            os.path.basename(self.source or 'scene'), cam, self._anim_line(),
            self._mode_line())

    def _anim_line(self) -> str:
        """Overlay line naming the current animation + play state (or '')."""
        if not getattr(self, '_animations', None):
            return ''
        name = self._anim_names[self._anim_index] if self._anim_index < len(
            self._anim_names) else 'animation'
        state = 'playing' if self._anim_playing else 'paused'
        extra = "  ([ ]: switch)" if len(self._animations) > 1 else ""
        return "anim [%d/%d] %s  (%s, k: pause)%s\n" % (
            self._anim_index + 1, len(self._animations), name, state, extra)

    def _mode_line(self) -> str:
        """Control hint reflecting the current walk/free-fly mode + the toggle."""
        if getattr(self, '_physics_on', False):
            return "walk: arrows/WASD move, space jump, f fly   g: free-fly"
        return "free-fly: arrows move, right-drag examine   g: walk (physics)"

    # -- lights / sky / framing -------------------------------------------
    @staticmethod
    def _sky() -> Background:
        """A bright, clear Mediterranean afternoon sky: strong blue zenith fading
        to a pale hazy horizon, over a sunlit stone ground."""
        return Background(
            skyColor=[(0.28, 0.50, 0.82), (0.45, 0.66, 0.90),
                      (0.72, 0.84, 0.96), (0.88, 0.93, 0.98)],
            skyAngle=[1.05, 1.40, 1.5708],
            groundColor=[(0.62, 0.58, 0.50), (0.74, 0.70, 0.60)],
            groundAngle=[1.5708],
        )

    def _default_lights(self, radius: float) -> list[Light]:
        r = radius
        # A bright, low, warm sun -- Mediterranean summer, ~6 pm -- is the single
        # shadow-caster and does the readable work; the (dimmed) analytic sky IBL
        # plus a faint sky-blue fill lift the shadows just enough to keep form.
        return [
            # golden low sun, well off to the side for long, distinct shadows
            DirectionalLight(direction=(-0.62, -0.42, -0.28), color=(1.0, 0.86, 0.62),
                             intensity=3.6, castShadows=True),
            # cool sky fill from the opposite side
            PointLight(location=(r * 2, r * 2.2, -r * 2), color=(0.55, 0.68, 0.92),
                       intensity=0.25, attenuation=(1, 0, 0), castShadows=False),
        ]

    def _frame(self, radius: float) -> None:
        """Frame the whole (centred) model, looking straight down -Z.

        A distance that fits a sphere of `radius` in the field of view, with a
        slight elevation + downward tilt. The model's own yaw supplies the
        three-quarter angle.

        `--margin`/`--elevation`/`--tilt` scale the fit distance, camera height
        and downward tilt. The defaults reproduce the built-in framing; a margin
        below 1 pulls the camera in so a wide/flat model (a sphere grid whose
        bounding sphere overestimates its visible footprint) fills the frame.
        """
        eye = getattr(self.config, 'eye', None)
        look_at = getattr(self.config, 'look_at', None)
        if eye is not None and look_at is not None:
            self._frame_eye_lookat(eye, look_at, radius)
            return
        margin = getattr(self.config, 'margin', None)
        margin = 1.15 if margin is None else margin
        elevation = getattr(self.config, 'elevation', None)
        elevation = 0.22 if elevation is None else elevation
        tilt = getattr(self.config, 'tilt', None)
        tilt = 0.10 if tilt is None else tilt
        fov = pi / 3.2
        distance = radius / max(1e-3, sin(fov / 2.0)) * margin
        self.platform.setFrustum(fov, None, max(1e-4, radius * 0.02), radius * 60.0)
        self.platform.setPosition((0.0, radius * elevation, distance))
        self.platform.setOrientation((1, 0, 0, tilt))

    def _frame_eye_lookat(self, eye: Any, target: Any, radius: float) -> None:
        """Place the camera at an explicit world-space ``eye`` looking at ``target``.

        For interior shots (e.g. standing inside Sponza looking across the arcade)
        that the on-axis auto-frame can't express. The camera looks down -Z at
        identity, so we yaw about +Y then pitch about the yawed X to aim it."""
        import numpy as np
        from OpenGLContext import quaternion
        e = np.asarray(eye, dtype='d')
        f = np.asarray(target, dtype='d') - e
        n = float(np.linalg.norm(f))
        if n < 1e-9:
            return
        f = f / n
        yaw = atan2(f[0], -f[2])                       # 0 when looking down -Z
        pitch = asin(max(-1.0, min(1.0, f[1])))        # + when looking up
        q = quaternion.fromXYZR(0, 1, 0, yaw) * quaternion.fromXYZR(1, 0, 0, pitch)
        fov = pi / 3.2
        self.platform.setFrustum(fov, None, max(1e-3, radius * 0.01), radius * 8.0)
        self.platform.setPosition(tuple(float(v) for v in e))
        self.platform.quaternion = q

    # -- capture / idle ---------------------------------------------------
    def _install_capture(self) -> None:
        if self.config.capture:
            self._settle = SettleCapture(
                self.config.capture, delay=self.config.capture_delay,
                min_frames=self.config.frames)

    # -- physics walk mode ------------------------------------------------
    def _setup_physics(self) -> None:
        """Install the walk/free-fly toggle.

        Physics walk mode (gravity + collision) replaces the free-fly camera; the
        ``g`` key toggles between them at runtime.  An initial viewpoint that drops
        the avatar inside geometry is therefore never a trap: press ``g`` to
        free-fly out, and ``g`` again to resume walking from wherever you flew to.
        Skipped for ``--capture`` and when the model has no scenegraph.
        """
        # ViewPlatformMixin's default Smooth navigator (arrows/mouse). We hand
        # control to it when physics is off, and unbind it while physics is on so
        # the two don't both write context.platform and fight -- which snaps the
        # camera back on key release (see plans/PHYSICS-COLLISION.md §Phase 5).
        self._free_manager = getattr(self, 'movementManager', None)
        if self.config.capture or getattr(self, 'sg', None) is None:
            return
        self.addEventHandler('keyboard', name='g', state=1, function=self._toggle_physics)
        # When the scene is still loading in the background, defer enabling physics to
        # _on_scene_ready (the empty placeholder scene has no walkable geometry).
        if self._scene_loaded and getattr(self.config, 'physics', False):
            if not self._set_physics(True):
                sys.stdout.write("Physics: no walkable geometry; using free-fly.\n")
        sys.stdout.write("Press 'g' to toggle walk (physics) / free-fly.\n")
        sys.stdout.flush()

    def _toggle_physics(self, event: Any = None) -> None:
        self._set_physics(not self._physics_on)

    def _set_physics(self, on: bool) -> bool:
        """Switch between walk (physics) and free-fly, keeping the camera put.

        Returns True on success; False if walk mode was requested but the model
        has no walkable geometry."""
        if on:
            first = self._physics is None
            if first and not self._ensure_physics():
                return False
            if not first:
                # resume walking from wherever free-fly left the camera
                self._sync_avatar_to_camera()
            # physics owns the camera: silence the free-fly navigator, then claim
            # the movement keys for the character controller.
            if self.movementManager is not None and self._free_manager is not None:
                self._free_manager.unbind(self)
                self.movementManager = None
            self._bind_physics_input()
            self._physics_on = True
        else:
            # hand the keys and camera back to the free-fly navigator; it picks up
            # from the current context.platform pose, so the view never jumps.
            if self.movementManager is None and self._free_manager is not None:
                self._free_manager.bind(self)
                self.movementManager = self._free_manager
            self._physics_on = False
        self._update_overlay()
        self.triggerRedraw(1)
        return True

    def _ensure_physics(self) -> bool:
        """Build the collision world + character once (curated initial spawn).

        Returns False if the model yields no walkable geometry."""
        if self._physics is not None:
            return True
        from OpenGLContext.physics.gltf_world import collision_world_from_scene
        from omi_physics.character import CharacterCapabilities
        from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
        world, bounds = collision_world_from_scene(self.sg)
        if bounds is None:
            return False
        lo, hi = bounds
        s = max(float(max(hi - lo)) / 40.0, 1e-3)     # scale the avatar to the model
        caps = CharacterCapabilities(
            walkSpeed=3.0 * s, runSpeed=6.0 * s, flySpeed=8.0 * s,
            jumpHeight=1.2 * s, stepHeight=0.4 * s, standHeight=1.8 * s,
            crouchHeight=1.0 * s, radius=0.3 * s, eyeHeight=1.6 * s)
        self._physics = PhysicsViewPlatform(world, caps, yaw=self.config.yaw,
                                            gravity=9.81 * s)
        # The speeds have to match the avatar, and the avatar is sized to the
        # model, so the modes are declared here rather than at startup.
        self.contextDefinition.movementModes = movement_modes(s)
        self._spawn_from_viewpoint_or_floor(lo, hi, caps)
        self._plast = self._now()
        self._physics.apply(self)
        return True

    def getNavigationPlatform(self) -> Any:
        """What the declared movement modes drive.

        The character controller while walking, so a mode moves the avatar and
        the camera follows it; the view platform otherwise, where the free-fly
        navigator still owns the camera.
        """
        if getattr(self, '_physics_on', False) and self._physics is not None:
            return self._physics
        return self.platform

    def _bind_physics_input(self) -> None:
        """(Re)bind the keys the declared movement modes name.

        Re-registered on every enable: binding/unbinding the free-fly navigator
        rewrites the shared arrow-key handlers, so physics must reclaim them.
        The modes decide what each key *means*; this only arranges for the
        events to arrive, since the sampler is fed by event dispatch itself.
        """
        navigation = self.getNavigation()
        if navigation is None:
            return
        for _name, binding in navigation.binding_table():
            for key in binding.keys:
                for state in (1, 0):
                    self.addEventHandler('keyboard', name=key, state=state,
                                         function=self._pkey)
        self.addEventHandler('keyboard', name='f', state=1, function=self._pfly)

    def _sync_avatar_to_camera(self) -> None:
        """Seat the avatar at the current free-fly camera pose (safe-bound)."""
        p = self._physics
        p.yaw = self._yaw_from_platform()
        p.pitch = 0.0
        p.bind_eye(tuple(self.platform.position[:3]))
        # nothing under an aerial camera: float there rather than plummet
        p.set_fly(not p.character.grounded)
        self._plast = self._now()

    def _yaw_from_platform(self) -> float:
        import numpy as np
        fwd = self.platform.quaternion * [0.0, 0.0, -1.0, 0.0]
        return float(np.arctan2(fwd[0], -fwd[2]))

    def _spawn_from_viewpoint_or_floor(self, lo: Any, hi: Any, caps: Any) -> None:
        """Stand the avatar on clear model floor, facing the first camera's heading.

        The model centre is often solid (a statue, thick walls), so sample several
        footprint positions and pick the first that lands grounded and unstuck.
        Camera viewpoints are often elevated, so we only borrow a camera's yaw for
        the initial heading; PageUp/PageDown teleports to viewpoints on request.
        """
        import numpy as np
        if self.viewpoints:
            self._physics.yaw = self._yaw_from_viewpoint(self.viewpoints[self.cam_index])
        cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
        # Prefer the authored camera viewpoints (curated, open spots) projected
        # straight down to the floor; then fall back to sampling the footprint for
        # models whose cameras are all aerial/outside.
        candidates: list[tuple[float, float]] = []
        for vp in self.viewpoints:
            p = vp.position
            if lo[0] <= p[0] <= hi[0] and lo[2] <= p[2] <= hi[2]:
                candidates.append((float(p[0]), float(p[2])))
        candidates.append((cx, cz))
        for frac in (0.25, 0.45, 0.65):             # interior → mid → outer rings
            for fx in np.linspace(-frac, frac, 5):
                for fz in np.linspace(-frac, frac, 5):
                    candidates.append((cx + fx * (hi[0] - lo[0]),
                                       cz + fz * (hi[2] - lo[2])))
        y = lo[1] + caps.standHeight
        best: Any = None                            # (clearance, -dist_from_centre, x, z)
        for x, z in candidates:
            self._physics.bind((x, y, z))
            ch = self._physics.character
            if not ch.grounded or ch.stuck or ch.flying:
                continue
            clear = self._clearance(ch, caps.radius)
            score = (clear, -((x - cx) ** 2 + (z - cz) ** 2))
            if best is None or score > best[0]:
                best = (score, x, z)
            if clear == 4:                          # fully open: good enough
                return
        if best is not None:
            self._physics.bind((best[1], y, best[2]))
        else:
            self._physics.bind((cx, y, cz))

    @staticmethod
    def _clearance(character: Any, radius: float) -> int:
        """How many of the 4 horizontal directions the avatar can actually *move*
        into (not merely not-overlap) — a point probe misses a wall that a step
        would hit, so test the real move-and-slide.  Avoids spawning wedged."""
        import numpy as np
        base = character.position
        reach = radius + 0.5
        clear = 0
        for d in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1)):
            dv = np.asarray(d, dtype='d')
            resolved, _ = character._push_out(base + dv * reach)
            if float(np.dot(resolved - base, dv)) > 0.5 * reach:   # moved *along* d
                clear += 1
        return clear

    @staticmethod
    def _yaw_from_viewpoint(vp: Any) -> float:
        import numpy as np
        from OpenGLContext import quaternion
        x, y, z, r = vp.orientation
        q = quaternion.fromXYZR(x, y, z, -r)      # setOrientation's convention
        R = np.asarray(q.matrix())[:3, :3]
        fwd = R.T @ np.array([0.0, 0.0, -1.0])
        return float(np.arctan2(-fwd[0], -fwd[2]))

    @staticmethod
    def _now() -> float:
        from time import time
        return time()

    def _pkey(self, event: Any) -> None:
        """Wake the frame loop; the sampler is fed by event dispatch itself."""
        self.triggerRedraw(1)

    def _pfly(self, event: Any) -> None:
        """Swap between the walking and flying modes.

        Flying is a property of the character controller as well as of the
        movement, so the mode change has to reach it.
        """
        navigation = self.getNavigation()
        if navigation is None or self._physics is None:
            return
        current = getattr(self.contextDefinition, 'movementMode', None)
        wanted = 'walk' if current is not None and current.name == 'fly' else 'fly'
        if navigation.select(wanted):
            self._physics.set_fly(wanted == 'fly')

    def _physics_step(self) -> None:  # pragma: no cover - per-frame physics walk loop
        now = self._now()
        dt = min(now - self._plast, 0.05)
        self._plast = now
        self.updateNavigation(dt)
        p = self._physics
        p.update(dt)
        p.apply(self)
        self.triggerRedraw(1)

    def OnIdle(self, *args: Any) -> int:  # pragma: no cover - interactive idle/redraw loop
        # A background scene load that finished gets applied here (render thread),
        # before anything else touches the scenegraph.
        if self._poll_pending_scene():
            return 1
        # Animation runs alongside walking/turntable: advance it first, then let
        # the movement/settle logic decide about redraws.
        animated = self._advance_animation()
        # A --capture run forces repeated redraws so the adaptive analytic-sky IBL
        # settles over several frames (as it does live) before we grab the frame.
        if self._settle is not None:
            self.triggerRedraw(1)
        elif self._physics_on:
            self._physics_step()
        elif self.config.turntable and self.model_xform is not None:
            from time import time
            # Spin from the model's default (per-model reference-facing) yaw, so a
            # profile that aims the model at the camera is honoured while rotating.
            base = self._default_model_rotation[3]
            start = cast(float, self._start)
            self.model_xform.rotation = (0, 1, 0, base + (time() - start) * 0.5)
            self.triggerRedraw(1)
        elif animated:
            self.triggerRedraw(1)
        return 1

    # -- overlay ----------------------------------------------------------
    def SwapBuffers(self) -> Any:  # pragma: no cover - GL swap, overlay draw + capture tick
        shader = self._active_shader()
        if shader is not None:
            if self._settle is None:              # a clean capture skips the HUD
                self._draw_overlay(shader)
            self._extra_overlay(shader)
        # Capture the freshly rendered back buffer *before* the swap (reading it
        # after the swap returns stale data in the dev-container).
        captured = self._settle.tick() if self._settle is not None else False
        if self._screenshot_pending:
            self._screenshot_pending = False
            self._save_screenshot()
        result = BaseContext.SwapBuffers(self)
        if captured:
            # Emit machine-readable capture stats for the regression runner to record:
            # how long the model took to load, and the median render rate reached.
            fps = ''
            fc = getattr(self, 'frameCounter', None)
            if fc is not None:
                try:
                    fps = fc.recentFps()
                except Exception:
                    fps = ''
            sys.stdout.write('CAPTURE_STATS load_seconds=%s fps=%s\n' % (
                getattr(self, '_load_seconds', ''), fps))
            sys.stdout.flush()
            self.OnQuit()
        return result

    def _extra_overlay(self, shader: Any) -> None:
        """Hook for subclasses to draw extra HUD elements. No-op by default."""

    @staticmethod
    def _active_shader() -> Any:
        from OpenGLContext.passes import renderpass
        flat = getattr(renderpass, 'FLAT', None)
        shader = getattr(flat, 'shader_program', None)
        if shader is None or getattr(shader, 'program', None) is None:
            return None
        return shader

    def _viewport(self) -> tuple[int, int] | None:
        vp = self.getViewPort()
        if not vp or not vp[0] or not vp[1]:
            return None
        return int(vp[0]), int(vp[1])

    def _draw_overlay(self, shader: Any) -> None:  # pragma: no cover - GL text overlay draw
        vp = self._viewport()
        if vp is None or not self.overlay_text:
            return
        tw, th = vp
        try:
            from OpenGLContext.scenegraph.text.shadertext import get_text_renderer
            renderer = get_text_renderer(16)
            renderer.render_text(
                self.overlay_text, x=10, y=th - 8 - renderer.char_height,
                shader_program=shader, viewport_width=tw, viewport_height=th,
                color=(1.0, 1.0, 1.0, 1.0), background_color=(0.0, 0.0, 0.0, 0.55),
            )
        except Exception:
            pass


def main(argv: list[str] | None = None) -> Any:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_cameras:
        src = _resolve_source(args.source or os.environ.get('GLTF'))
        if src is None:
            parser.error('no glTF/GLB file or URL given (pass a path/URL or set GLTF=...)')
        scene = _load_source(src)
        if not scene.cameras:
            sys.stdout.write("(no cameras defined in %s)\n" % os.path.basename(src))
        for i, pose in enumerate(scene.cameras):
            sys.stdout.write("%d: %s\n" % (i, pose.get('name') or 'camera'))
        return 0

    if not (args.source or os.environ.get('GLTF')):
        parser.error('no glTF/GLB file or URL given (pass a path/URL or set GLTF=...)')

    apply_render_env(args)
    TestContext.config = args
    return TestContext.ContextMainLoop(size=args.size) if args.size \
        else TestContext.ContextMainLoop()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
