#! /usr/bin/env python
"""PBR glTF sample browser (``oglc-gltf-demo``) -- a thin wrapper over the viewer.

Streams every model in the KhronosGroup/glTF-Sample-Models 2.0 catalogue and shows
it with the shared ``oglc-gltf`` viewer's PBR scene/lighting/framing, adding only what
is specific to browsing: catalogue navigation and the reference-screenshot thumbnail
overlaid top-right so a rendering can be compared against the reference.

    n / Page Down   next model
    p / Page Up     previous model
    F2              save a screenshot (iso-dated PNG in the current directory)
    Alt + s         the engine's own screenshot key, named for the program and
                    written to the current directory too
    Alt + f         the developer overlay -- frame rate, renderer features and
                    what the frame cost (see docs/hud.html)

(The arrow keys are left free for camera navigation.)

Models are downloaded on a background thread, so switching models never freezes the
window: the current model keeps rendering (with a "Loading ..." overlay) until the
next one is decoded and ready to upload to the card.

The model name is drawn top-left (white); a download/decode failure is shown there
in red. Models are centred, auto-framed and slowly turned -- embedded cameras are
authored for the model's original placement and don't survive centring, so the
viewer's ``--no-cameras`` framing is used.

Run:  oglc-gltf-demo
Start elsewhere:  oglc-gltf-demo --model DamagedHelmet  (or MODEL=DamagedHelmet)

Every ``oglc-gltf`` command-line option applies (``--shadows/--no-shadows``,
``--lights``, ``--ibl-intensity``, ...); see ``oglc-gltf-demo -h``.
"""
import os
import sys
from dataclasses import dataclass
from typing import Any, Sequence

os.environ.setdefault('OPENGLCONTEXT_SHADOWS', '1')

from OpenGLContext.bin.view import apply_render_env, build_parser
from OpenGLContext.ui.gallery import Picture
from OpenGLContext.ui.hudwidgets import HUDGroup, Readout
from OpenGLContext.viewer.sceneviewer import ViewerContext
from OpenGLContext.viewer import ViewerOptions
from OpenGLContext.loaders import gltf
from OpenGLContext.loaders import gltf_demos


# -- per-model demo profiles -------------------------------------------------
# The browser can't frame every model the same way: an object (a helmet) wants a
# slow turntable while *facing* the camera; a building (Sponza) wants to be walked
# through from the courtyard; a city wants a free-fly camera *inside* it. This
# table sets, per model, the facing yaw, whether to turntable, and whether to run
# physics (and start flying). Unlisted models get DEFAULT_PROFILE. Grow it from the
# conformance harness (plans/GLTF-DEMO-CONFORMANCE.md) as reference poses are dialed
# in; --no-rotate / --yaw / --physics still override per run.

@dataclass(frozen=True)
class ModelProfile:
    yaw: float = 0.0          # facing rotation about +Y (radians) on first load
    turntable: bool = True    # slowly rotate the model
    physics: bool = False     # walk/fly the scene with collision
    fly: bool = False         # start in free-fly (vs grounded walk) when physics on
    background: str = ''      # '' (black), 'sky', or 'cube' (env cubemap skybox)
    bloom: bool = False        # HDR bloom (emissive glow) -- for emissive-heavy demos


DEFAULT_PROFILE = ModelProfile()

# Sub-demos whose materials need a lit environment to read correctly: transmissive
# glass refracts the backdrop (a black one renders rough glass opaque), metals
# reflect it, and a lamp lit only by its own bulb meters an exposure that leaves
# everything the bulb does not reach black. The roster is derived from the shared
# per-scene table (gltf_demos), so the demo and the capture harness cannot drift on
# which models need one; the demo lights them with the cheap analytic 'sky' (see
# the loop below).
_ENV_BACKGROUND = tuple(sorted(gltf_demos.ENV_BACKGROUND_MODELS))

# Emissive-heavy sub-demos whose reference shows a bloom/glow. Bloom is HDR + a
# post-process (OPENGLCONTEXT_BLOOM); it is enabled per-model so it does not change
# the tone-mapping of the (majority) non-emissive demos.
_BLOOM_MODELS = ('EmissiveStrengthTest', 'IridescenceLamp')

MODEL_PROFILES = {
    # Architecture / scenes: walk or fly, no turntable. "Start in the courtyard" /
    # "inside the city" is handled by the character spawn sampling clear floor.
    'Sponza': ModelProfile(turntable=False, physics=True),
    'VirtualCity': ModelProfile(turntable=False, physics=True, fly=True),
    # Objects (DamagedHelmet, Duck, ...) are correct at the default yaw 0 (verified:
    # the helmet's visor faces the camera) with a slow turntable, so they need no
    # entry. Add a `yaw=` here only for a model the conformance harness shows facing
    # away at 0 -- do not guess (a wrong yaw turns a front-facing model backwards).
}
# Fold the env-background list into the profile table (same mechanism as yaw/physics).
# 'sky' (the lit gradient) is used rather than 'cube': it reliably gives glass a lit
# backdrop to refract (a black one renders rough glass opaque) and metals a lit
# reflection, without the image-cube skybox's per-face load cost in the browser.
for _name in _ENV_BACKGROUND:
    _base = MODEL_PROFILES.get(_name, DEFAULT_PROFILE)
    MODEL_PROFILES[_name] = ModelProfile(
        yaw=_base.yaw, turntable=_base.turntable, physics=_base.physics,
        fly=_base.fly, background='sky', bloom=_base.bloom)
for _name in _BLOOM_MODELS:
    _base = MODEL_PROFILES.get(_name, DEFAULT_PROFILE)
    MODEL_PROFILES[_name] = ModelProfile(
        yaw=_base.yaw, turntable=_base.turntable, physics=_base.physics,
        fly=_base.fly, background=_base.background, bloom=True)


def default_env_prefix() -> str | None:
    """Path prefix of the bundled demo environment cubemap (or an override).

    ``OPENGLCONTEXT_ENV_CUBEMAP`` wins; otherwise the faces shipped under the
    package's ``resources/environment`` are used so the ``cube`` background works
    out of the box. Returns None if no face set is found.
    """
    override = os.environ.get('OPENGLCONTEXT_ENV_CUBEMAP', '').strip()
    if override:
        return override
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # OpenGLContext/
    prefix = os.path.join(here, 'resources', 'environment', 'pimbackground_')
    if os.path.exists(prefix + 'UP.jpg'):
        return prefix
    return None


def profile_for(name: str) -> ModelProfile:
    """Return the :class:`ModelProfile` for a model name (default if unlisted)."""
    return MODEL_PROFILES.get(name, DEFAULT_PROFILE)


def resolve_bloom(name: str) -> bool:
    """Whether the per-model profile asks for HDR bloom (emissive glow)."""
    return profile_for(name).bloom


def resolve_background(config: ViewerOptions, name: str) -> Any:
    """Background spec for a model: explicit --background wins, else the per-model
    profile ('cube'/'sky'), else the demo default (black 'none').

    The fallback is `_background_default`, the run's own default, not the live
    `config.background`: the browser writes each model's resolved background back
    onto the config, so reading it here would latch an env model's 'sky' onto
    every plain model browsed after it -- and a self-lit scene shown against an
    environment loses its metered exposure and clips to white.
    """
    if getattr(config, '_background_explicit', False):
        return config.background
    prof = profile_for(name)
    if prof.background == 'cube':
        return 'cube'
    if prof.background == 'sky':
        return 'sky'
    return getattr(config, '_background_default', config.background)


def demos_first(catalogue: Sequence[Any]) -> list:
    """The catalogue reordered so the conformance fixtures come last.

    Most of the Khronos sample set exists to exercise one glTF feature -- a bare
    triangle, a sparse accessor, forty ``Compare*`` grids -- and stepping
    through those to reach something worth looking at is not browsing.  Which is
    which comes from the shared table (:mod:`OpenGLContext.loaders.gltf_demos`),
    so this and the viewer's shelf cannot disagree.

    Nothing is dropped: the fixtures are still there, they are just not what
    opens first.  Each half keeps the catalogue's own order.
    """
    entries = list(catalogue)
    demos = [entry for entry in entries
             if not gltf_demos.scene_for(entry['name']).feature_test]
    fixtures = [entry for entry in entries
                if gltf_demos.scene_for(entry['name']).feature_test]
    return demos + fixtures


def resolve_start_index(names: Sequence[str], start: str) -> int:
    """Catalogue index to open on for a ``--model``/``MODEL`` selector.

    The selector is a model name, a 0-based catalogue index (wrapped, so `-1`-ish
    over-runs still land on a model), or empty for the first model. An unknown
    name opens the first model rather than failing -- the catalogue is fetched
    from the network and its contents vary.
    """
    start = (start or '').strip()
    if not start or not names:
        return 0
    if start.isnumeric():
        return int(start) % len(names)
    return names.index(start) if start in names else 0


def resolve_view(config: ViewerOptions, name: str) -> tuple[float, bool]:
    """(yaw, turntable) for a model, honouring --no-rotate / explicit --turntable /
    explicit --yaw over the per-model profile."""
    prof = profile_for(name)
    if getattr(config, 'no_rotate', False):
        turntable = False
    elif getattr(config, '_turntable_explicit', False):
        turntable = True
    else:
        turntable = prof.turntable
    yaw = config.yaw if getattr(config, '_yaw_explicit', False) else prof.yaw
    return yaw, turntable


def resolve_physics(config: ViewerOptions, name: str) -> tuple[bool, bool]:
    """(physics, fly) for a model. A --capture run never walks (deterministic
    frame); an explicit --physics/--no-physics overrides the per-model profile."""
    prof = profile_for(name)
    if getattr(config, 'capture', None):
        return False, False
    if getattr(config, '_physics_explicit', False):
        return bool(config.physics), prof.fly
    return prof.physics, prof.fly


#: How big the reference thumbnail is, in pixels at the reference font size.
REFERENCE_SIZE = (320, 240)


class ReferencePicture(HUDGroup):
    """The current model's own reference screenshot, labelled, in the corner.

    What makes this a *comparison* rather than a gallery: the rendering and the
    picture it should look like, on screen together.  It is an ordinary HUD
    group, so the picture cache behind it fetches the URL, decodes it off the
    render thread and evicts it when the browser has moved on.
    """

    PROTO = 'ReferencePicture'

    def __init__(self, **named: Any) -> None:
        picture = Picture(width=REFERENCE_SIZE[0], height=REFERENCE_SIZE[1])
        named.setdefault('anchor', 'top-right')
        named.setdefault('children', [picture, Readout(label='reference',
                                                       align='center')])
        super(ReferencePicture, self).__init__(**named)
        self.picture = picture

    @property
    def url(self) -> str:
        return str(self.picture.url)

    @url.setter
    def url(self, value: str) -> None:
        self.picture.url = value or ''
        # An entry with no reference of its own shows nothing rather than the
        # last model's picture with the wrong label under it.
        self.visible = bool(value)


class TestContext(ViewerContext):
    """The viewer, browsing the sample catalogue instead of one file."""

    def hasSceneToShow(self) -> bool:
        """Always: the catalogue is what this browser shows, not one file."""
        return True

    def prepareSource(self) -> None:
        self.source = None
        self.overlayError = False
        self._ref_current: Any = None
        try:
            self.catalog: Any = demos_first(gltf.fetch_sample_catalog())
        except Exception as err:
            print("Could not fetch the model catalogue: %s" % err)
            self.catalog = demos_first(
                [{'name': n, 'display': n, 'screenshot_url': None}
                 for n in gltf.SAMPLE_MODELS])
        start = getattr(self.options, 'model', None) or os.environ.get('MODEL', '')
        self.index = resolve_start_index([e['name'] for e in self.catalog], start)

    def loadScene(self) -> Any:
        entry = self.catalog[self.index]
        label = "[%d/%d] %s" % (self.index + 1, len(self.catalog), entry['display'])
        self._ref_current = entry['name']
        print("Loading %s ..." % label)
        try:
            scene = gltf.load_sample(entry['name'])
        except Exception as err:
            self._label = "%s\nFAILED: %s" % (label, str(err).splitlines()[0][:50])
            self.overlayError = True
            print("  " + self._label.replace("\n", "  "))
            return None
        self._label = label
        self.overlayError = False
        return scene

    # -- async catalogue loading -----------------------------------------
    def requestInitialScene(self) -> None:
        """Pull the initial catalogue model in the background instead of a file."""
        self._request_current_model()

    def _request_current_model(self) -> None:
        """Kick off a background load of the model at ``self.index``. The window keeps
        rendering the previous model (with a "Loading ..." overlay) until it lands."""
        entry = self.catalog[self.index]
        name = entry['name']
        label = "[%d/%d] %s" % (self.index + 1, len(self.catalog), entry['display'])
        self._pending_name = name
        self._pending_label = label
        print("Loading %s ..." % label)
        self.requestScene(lambda: gltf.load_sample(name),
                            label="Loading %s ..." % label)

    def applyLoadedScene(self, scene: Any) -> None:
        # buildScenegraph reads _ref_current for the per-model profile, so set the
        # newly loaded model's identity before building.
        self._ref_current = self._pending_name
        self._label = self._pending_label
        self.overlayError = False
        self.buildScenegraph(scene)
        self.onSceneReady()

    def applyFailedLoad(self, error: BaseException | None) -> None:
        self._ref_current = self._pending_name
        self.overlayError = True
        msg = str(error).splitlines()[0][:50] if error else 'load failed'
        self._label = "%s\nFAILED: %s" % (self._pending_label, msg)
        self.overlayText = self._label
        print("  " + self._label.replace("\n", "  "))

    def onSceneReady(self) -> None:
        self.sceneLoaded = True
        self._apply_physics_profile()

    def buildScenegraph(self, scene: Any) -> None:
        # Apply the per-model facing/turntable/background BEFORE the base builds the
        # scenegraph (it reads the framing options and builds the background there).
        self.options.yaw, self.options.turntable = resolve_view(
            self.options, self._ref_current)
        self.options.background = resolve_background(self.options, self._ref_current)
        # Bloom is read per frame from the env var, so toggling it per model works.
        os.environ['OPENGLCONTEXT_BLOOM'] = '1' if resolve_bloom(self._ref_current) else '0'
        ViewerContext.buildScenegraph(self, scene)
        self.overlayText = self._label

    def setupWalking(self) -> None:
        # Enable physics for the *initial* model only if its profile asks for it.
        physics, fly = resolve_physics(self.options, getattr(self, '_ref_current', ''))
        self.options.physics = physics
        ViewerContext.setupWalking(self)
        if physics and self.physicsPlatform is not None:
            self._physics_scene = self.sg
            if fly:
                self.physicsPlatform.set_fly(True)

    def _apply_physics_profile(self) -> None:
        """Turn physics on/off for the newly loaded model per its profile.

        Called on model *switch* (after `setupWalking` has captured the free-fly
        manager). Rebuilds the collision world when the scene changed so a physics
        model gets its own world, and hands control back to free-fly otherwise.
        """
        if getattr(self, 'sg', None) is None or self.options.capture:
            return
        physics, fly = resolve_physics(self.options, self._ref_current)
        if physics:
            if getattr(self, '_physics_scene', None) is not self.sg:
                self.physicsPlatform = None   # force a rebuild for this scene
            if self.enablePhysics(True):
                self._physics_scene = self.sg
                if fly and self.physicsPlatform is not None:
                    self.physicsPlatform.set_fly(True)
        elif self.physicsWalking:
            self.enablePhysics(False)

    # Catalogue navigation keys. Deliberately NOT the arrow keys: those drive
    # free-fly camera movement, so binding them to next/prev model made walking
    # around a model a pain (every turn also jumped to another model).
    NEXT_MODEL_KEYS = ('n', '<pagedown>')
    PREV_MODEL_KEYS = ('p', '<pageup>')

    # -- catalogue navigation --------------------------------------------
    def setupCallbacks(self) -> None:  # pragma: no cover - binds live event handlers
        # Skip the viewer's PageUp/PageDown viewpoint bindings (this browser has no
        # per-model cameras); n/p and PageUp/PageDown advance the *model* instead.
        from OpenGLContext import testingcontext
        testingcontext.getInteractive().setupCallbacks(self)
        for key in self.NEXT_MODEL_KEYS:
            self.addEventHandler('keyboard', name=key, function=self._next_model)
        for key in self.PREV_MODEL_KEYS:
            self.addEventHandler('keyboard', name=key, function=self._prev_model)

    def _next_model(self, event: Any = None) -> None:
        self._go(1)

    def _prev_model(self, event: Any = None) -> None:
        self._go(-1)

    def _go(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.catalog)
        self._request_current_model()

    # -- the reference thumbnail -----------------------------------------
    def setupCaption(self):
        """The caption, plus the reference screenshot beside it.

        The reference is what makes this a comparison rather than a gallery, so
        it is a picture in the same HUD layer as the caption -- one tree, one
        batched draw, and the cache behind it downloads and evicts on its own.
        """
        layer = ViewerContext.setupCaption(self)
        self.referencePicture = ReferencePicture()
        layer.children = list(layer.children) + [self.referencePicture]
        return layer

    def referenceURL(self) -> str:
        """Where the current model's reference screenshot is, or ''."""
        entry = self.catalog[self.index] if self.catalog else {}
        return (entry.get('screenshot_url') or '') if not self.overlayError else ''

    def updateOverlay(self) -> None:
        ViewerContext.updateOverlay(self)
        self.referencePicture.url = self.referenceURL()


def demo_config(argv: list[str] | None = None) -> ViewerOptions:
    """Parse + massage the browser's config (no GL). Separated so it is testable.

    The browser centres + turntables every model and ignores embedded cameras, so
    it also defaults to **free-fly, not physics**: a turntable model has no ground,
    and walk mode just drops the avatar until the model is out of view. An explicit
    ``--physics``/``--no-physics`` on the command line is still honoured.
    """
    parser = build_parser(prog='oglc-gltf-demo')
    parser.add_argument('--model', default=os.environ.get('MODEL', ''),
                        metavar='NAME|INDEX',
                        help='catalogue model to open on, by sample name '
                             '(e.g. DamagedHelmet) or 0-based index; '
                             'default: the MODEL env var, else the first model')
    args = parser.parse_args(argv, namespace=ViewerOptions())
    args.no_cameras = True
    args.turntable = True
    # Most models read cleanest on black; the per-model profile (resolve_background)
    # injects a lit/cube background only for the sub-demos that need one (glass to
    # refract, metals to reflect). An explicit --background always wins.
    if args.background is None:
        args.background = 'none'
    tokens = sys.argv[1:] if argv is None else argv
    # Record which view/physics knobs the user set explicitly, so the per-model
    # profiles (resolve_view/resolve_physics) can defer to them.
    args._physics_explicit = any(t in ('--physics', '--no-physics') for t in tokens)
    args._turntable_explicit = '--turntable' in tokens
    args._yaw_explicit = '--yaw' in tokens
    args._background_explicit = '--background' in tokens
    args._background_default = args.background
    if not args._physics_explicit:
        args.physics = False
    # A --capture run wants a fixed, reference-comparable orientation; the
    # turntable would spin the model away from the reference pose. Freeze it for
    # captures (honour an explicit --turntable).
    if args.capture and not args._turntable_explicit:
        args.turntable = False
    return args


def apply_environment(args: ViewerOptions) -> None:
    """Set the render env so metals reflect a real environment in the browser.

    Loads the bundled environment cubemap into the IBL probe and pins full IBL, so
    metals / dielectric specular / sheen reflect it instead of a near-black env
    (SpecularTest, ToyCar, MetalRoughSpheres, NegativeScaleTest, ...). Safe on heavy
    models (the earlier stall was the CubeBackground skybox, now built only for a
    'cube' background). Reflections read too dim at the shadow-tuned 0.4 IBL
    intensity, so lift it for browsing (an explicit --ibl-intensity still wins).
    """
    # An explicit --environment (a cubemap prefix, an .hdr, or a bundled HDRI name)
    # is owned entirely by apply_render_env; only fall back to the bundled cubemap
    # when the user named no environment of their own.
    env = default_env_prefix()
    if env and not args.environment:
        os.environ.setdefault('OPENGLCONTEXT_ENV_CUBEMAP', env)
        os.environ.setdefault('OPENGLCONTEXT_IBL', 'full')
    if args.ibl_intensity is None:
        os.environ['OPENGLCONTEXT_IBL_INTENSITY'] = '0.9'


def main(argv: list[str] | None = None) -> Any:
    args = demo_config(argv)
    apply_environment(args)
    apply_render_env(args)             # an explicit --ibl-intensity still wins here
    TestContext.options = args
    return TestContext.ContextMainLoop(size=args.size) if args.size \
        else TestContext.ContextMainLoop()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
