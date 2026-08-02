"""A viewer you can embed, for whatever the adapters can open.

:class:`ViewerContext` opens a source -- from disk or over http(s) -- and shows
it: lit by its own lights or by a default rig, against the environment its
metals reflect, framed so the whole thing is visible, with its cameras and
animations reachable and walkable if you want to walk it.  ``oglc-view`` is this
class plus a command line.

    from OpenGLContext.viewer import ViewerContext, ViewerOptions

    class MyViewer(ViewerContext):
        options = ViewerOptions(source='model.glb', physics=True)

    MyViewer.ContextMainLoop()

Which format a source is in is not this module's business: a
:class:`~OpenGLContext.viewer.adapters.base.SceneAdapter`, chosen from the
source itself, reads the file and answers the handful of questions asked of
every scene.  Adding a format is writing one of those, not editing this.

Everything the viewer can be told is a
:class:`~OpenGLContext.viewer.options.ViewerOptions` field.  What it *does* is a
handful of methods meant to be overridden:

``prepareSource()``
    Where the scene comes from.  A browser that walks a catalogue has no single
    source and overrides this to nothing.
``loadScene()``
    Produce the scene.  Runs on a **worker thread**, so it must not touch GL.
``requestInitialScene()``
    What to load first.
``buildScenegraph(scene)``
    Turn a loaded scene into ``self.sg``.  Called again for each new model.
``onSceneReady()``
    Just after a scene has been built, on the render thread.
``buildPhysicsWorld()``
    Where the collision world comes from, if not from ``self.sg``.

The pieces underneath are useful on their own and live beside this module:
:mod:`~OpenGLContext.viewer.adapters` (what a source is and how to read it),
:mod:`~OpenGLContext.viewer.asyncscene` (loading without freezing),
:mod:`~OpenGLContext.viewer.framing` (where to put the camera),
:mod:`~OpenGLContext.viewer.environment` (sky and skybox),
:mod:`~OpenGLContext.viewer.overlay`, :mod:`~OpenGLContext.viewer.capture`, and
:class:`~OpenGLContext.move.physicswalk.PhysicsWalkMixin`, which every
interactive context has.

See [docs/gltf.html](../../docs/gltf.html).
"""
import os
import sys
from typing import (
    TYPE_CHECKING, Any, List, NamedTuple, Optional, Sequence, Tuple, cast,
)

from OpenGLContext import testingcontext
from OpenGLContext.scenegraph.light import DirectionalLight, Light, PointLight
from OpenGLContext.scenegraph.scenegraph import SceneGraph
from OpenGLContext.scenegraph.transform import Transform
from OpenGLContext.viewer import debug
from OpenGLContext.viewer import environment as env
from OpenGLContext.viewer import framing
from OpenGLContext.viewer.adapters import (
    SceneAdapter, UnknownSourceType, adapter_for, adapter_named,
)
from OpenGLContext.ui.overlay import OverlayMixin
from OpenGLContext.viewer.asyncscene import AsyncSceneMixin
from OpenGLContext.viewer.capture import SettleCaptureMixin
from OpenGLContext.viewer.options import ViewerOptions
from OpenGLContext.viewer.caption import CaptionMixin
from OpenGLContext.viewer.overlay import ScreenshotMixin
from OpenGLContext.viewer.screens import ViewerScreensMixin
from OpenGLContext.viewer.source import resolve_source

if TYPE_CHECKING:
    from OpenGLContext.context import Context as _Base
else:
    _Base = testingcontext.getInteractive()

__all__ = ['KeyBinding', 'SceneViewerMixin', 'ViewerContext']

#: How fast the turntable turns, in radians per second.
TURNTABLE_RATE = 0.5
#: Longest animation step taken from wall time, so a stall does not jump the pose.
MAX_ANIMATION_STEP = 0.1

#: Modifier states, in the order a keyboard event reports them.  Naming them is
#: worth it: the two that are not shift are one position apart and a binding that
#: asks for the wrong one is silent rather than wrong.
NO_MODIFIERS = (False, False, False)
CONTROL = (False, True, False)


class KeyBinding(NamedTuple):
    """One key the viewer answers to.

    ``method`` is named rather than bound so the table can be a class attribute:
    the function to call is the one on *this* viewer, found when the callbacks
    are set up.  ``description`` says what the key does, in a form fit to list.
    """

    name: str
    method: str
    description: str
    modifiers: Tuple[bool, bool, bool] = NO_MODIFIERS
    #: Key state to answer to: 0 is the release.  Every one of these does a
    #: discrete thing once, and a held key repeats around twenty times a second
    #: -- twenty models loaded, twenty cameras past the one wanted.  The release
    #: happens exactly once however long the key is down.
    state: int = 0


class SceneViewerMixin(AsyncSceneMixin, CaptionMixin, ScreenshotMixin,
                       SettleCaptureMixin, ViewerScreensMixin):
    """Showing one scene: assembly, cameras, animation and the caption."""

    #: What to show and how.  A class attribute so a subclass can simply set it.
    options: ViewerOptions = ViewerOptions()

    #: Resolved scene source (path or URL).
    source: Optional[str] = None
    #: How to read it.  Chosen from the source by :meth:`prepareSource`; a host
    #: with scenes of its own sets one directly.
    adapter: SceneAdapter = SceneAdapter()
    #: Radius of the loaded model, which sizes the framing and the light rig.
    radius: float = 1.0
    #: The transform the whole model hangs from, and which the turntable turns.
    modelTransform: Optional[Transform] = None
    #: ``Viewpoint`` nodes for the model's own cameras, in document order.
    viewpoints: List[Any]
    #: Which of them is bound.
    cameraIndex: int = 0

    #: The options this viewer started with, before any library entry's.
    _baseOptions: Optional[ViewerOptions] = None
    #: The shelf, built on first use.
    _library: Any = None
    #: The scene as the adapter loaded it, kept because it is what knows how to
    #: build an animation player wired to its own skins and morph targets.
    scene: Any = None
    #: The library entry currently open, or None when the source came from
    #: somewhere else.  It is what PageUp/PageDown step along.
    libraryEntry: Any = None

    if TYPE_CHECKING:
        sg: Any
        platform: Any
        contextDefinition: Any
        physicsYaw: float
        physicsWalking: bool

        def addEventHandler(self, kind: str, **named: Any) -> Any: ...
        def triggerRedraw(self, force: int = 0) -> Any: ...
        def getSceneGraph(self) -> Any: ...
        def setupPhysics(self, enable: bool = False) -> bool: ...
        def enablePhysics(self, on: bool = True) -> bool: ...
        def stepPhysics(self, dt: Optional[float] = None) -> None: ...
        def moveAvatarToViewpoint(self, viewpoint: Any) -> None: ...
        def getNavigation(self) -> Any: ...

    # -- start-up ---------------------------------------------------------
    def OnInit(self) -> None:  # pragma: no cover - live GL context setup
        self.viewpoints = []
        self.cameraIndex = 0
        self.modelTransform = None
        self._cameraNames: List[str] = []
        self._turntableStart = self._now()
        self._defaultModelRotation: Sequence[float] = (0, 1, 0, 0.0)
        self._animations: List[Any] = []
        self._animationNames: List[str] = []
        self._animationIndex = 0
        self._animationPlaying = self.options.animate
        self._animationClock = 0.0
        self._animationLast: Optional[float] = None
        self._player: Any = None
        self.setupAsyncScene()
        self.setupCaption()
        self.setupScreenshots()
        self.prepareSource()
        self.setupCapture(self.options.capture, self.options.capture_delay,
                          self.options.frames)
        # A captured frame is the scene and nothing else.
        self.showCaption(not self.capturing)
        if not self.capturing:
            debug.install(self)
            self.setupScreens()
        if self.capturing:
            # A capture has to be deterministic, and the settle logic has to see
            # the model, so it is loaded before the loop starts rather than
            # alongside it.
            from time import perf_counter
            started = perf_counter()
            scene = self.loadScene()
            self.loadSeconds = round(perf_counter() - started, 3)
            if scene is not None:
                self.buildScenegraph(scene)
                self.sceneLoaded = True
            elif getattr(self, 'sg', None) is None:
                self.sg = SceneGraph(children=[])
            self.setupWalking()
        else:
            # Show an empty scene at once and pull the model in behind it, so the
            # window is never frozen on a download.
            self.sg = SceneGraph(children=[])
            self.setupWalking()
            self.requestInitialScene()

    # -- where the scene comes from ---------------------------------------
    def prepareSource(self) -> None:
        """Resolve :attr:`source` and :attr:`adapter` from the options.

        **Nothing to open is not an error**: a viewer with no source shows its
        library instead, which is what makes ``oglc-view`` on its own a program
        rather than a usage message.  A source that was *named* and cannot be
        opened is an error, and it exits saying what it can open -- the answer
        to "not that" is usually "then what".

        A subclass that gets its scenes elsewhere -- a catalogue, a generator --
        overrides this.
        """
        named = self.options.source or os.environ.get('GLTF')
        self.source = resolve_source(named)
        if self.source is None:
            if named:
                sys.stderr.write("ERROR: file not found: %s\n" % (named,))
                raise SystemExit(2)
            return
        try:
            self.adapter = (adapter_named(self.options.format)
                            if self.options.format
                            else adapter_for(self.source))
        except UnknownSourceType as error:
            sys.stderr.write("ERROR: %s\n" % (error,))
            raise SystemExit(2) from None
        self.adapter.configure(self.options)

    def loadScene(self) -> Any:
        """Produce the scene to show.  **Runs on a worker thread: no GL here.**"""
        sys.stdout.write("Loading %s ...\n" % self.source)
        sys.stdout.flush()
        return self.adapter.load(cast(str, self.source))

    def requestInitialScene(self) -> None:
        """Start loading whatever is shown first, if there is anything."""
        if self.source is None:
            return
        self.requestScene(self.loadScene, self.loadingLabel())

    # -- opening something else -------------------------------------------
    def openSource(self, source: str, format: Optional[str] = None) -> bool:
        """Show ``source`` instead of what is showing.  False if it cannot.

        The load runs in the background like the first one does, so the window
        keeps drawing the scene it already has while the next one arrives, and
        :class:`~OpenGLContext.viewer.asyncscene.AsyncSceneMixin` drops a load
        that a later one has overtaken -- which is what makes clicking quickly
        through a library safe.
        """
        resolved = resolve_source(source)
        if resolved is None:
            self.overlayError = True
            self.overlayText = "Not found: %s" % (source,)
            sys.stderr.write("ERROR: file not found: %s\n" % (source,))
            return False
        try:
            adapter = (adapter_named(format) if format
                       else adapter_for(resolved))
        except UnknownSourceType as error:
            self.overlayError = True
            self.overlayText = "%s" % (error,)
            sys.stderr.write("ERROR: %s\n" % (error,))
            return False
        self.source, self.adapter = resolved, adapter
        # Opening a source directly -- a typed address, a file on the command
        # line -- is leaving the shelf behind, so there is no longer a list to
        # step along.  openEntry sets it again straight after this.
        self.libraryEntry = None
        adapter.configure(self.options)
        self.requestScene(self.loadScene, self.loadingLabel())
        return True

    def openEntry(self, entry: Any) -> bool:
        """Show a :class:`~OpenGLContext.viewer.library.Entry` from the library.

        The entry's own options are applied first -- the roster records how each
        scene has to be shown, and a model framed for one is framed wrongly for
        the next -- and they are applied to a *fresh* copy of the options the
        viewer started with, so nothing accumulates as someone browses.
        """
        self.options = self.baseOptions.replace(**dict(entry.options))
        opened = self.openSource(entry.source)
        if opened:
            self.libraryEntry = entry
        return opened

    @property
    def baseOptions(self) -> ViewerOptions:
        """The options this viewer was configured with, before any entry's.

        Remembered on first use, since :meth:`openEntry` overwrites
        :attr:`options` and would otherwise fold each entry's framing into the
        next one's starting point.
        """
        if self._baseOptions is None:
            self._baseOptions = self.options.replace()
        return self._baseOptions

    def stepLibrary(self, delta: int) -> None:
        """Open the next entry along in the list the current one came from.

        Its own **category**, since that is the list that was being browsed,
        and wrapping, so the end is not a dead stop.

        Nothing happens when the current scene did not come from the shelf --
        a file named on the command line, an address typed into the menu --
        because there is no list it is part of.
        """
        entry = self.libraryEntry
        if entry is None:
            return
        shelf = self.viewerLibrary().inCategory(entry.category)
        if not shelf:
            return
        try:
            index = [item.name for item in shelf].index(entry.name)
        except ValueError:
            index = 0
        self.openEntry(shelf[(index + delta) % len(shelf)])

    def nextInLibrary(self, event: Any = None) -> None:
        self.stepLibrary(1)

    def previousInLibrary(self, event: Any = None) -> None:
        self.stepLibrary(-1)

    # -- what it can offer to open ----------------------------------------
    def viewerLibrary(self) -> Any:
        """The shelf this viewer offers.  Override to curate your own.

        Built once and kept, because the pictures are filled in from a catalogue
        that has to be fetched and nobody wants to wait for it twice.
        """
        if self._library is None:
            from OpenGLContext.viewer.library import default_library
            self._library = default_library()
        return self._library

    def loadingLabel(self) -> str:
        """What the caption says while the first model is on its way."""
        return "Loading %s ..." % os.path.basename(self.source or 'scene')

    # -- the handover from the loader thread ------------------------------
    def onSceneLoading(self, label: str) -> None:
        self.overlayText = label
        self.overlayError = False

    def applyLoadedScene(self, scene: Any) -> None:
        self.buildScenegraph(scene)
        self.onSceneReady()

    def applyFailedLoad(self, error: Optional[BaseException]) -> None:
        if getattr(self, 'sg', None) is None:
            self.sg = SceneGraph(children=[])
        self.overlayError = True
        message = str(error).splitlines()[0][:60] if error else 'load failed'
        self.overlayText = "FAILED: %s" % message
        sys.stderr.write("Load failed: %s\n" % (error,))
        sys.stderr.flush()

    def onSceneReady(self) -> None:
        """A scene has been built.  Give walking a world to work with.

        The collision world is dropped rather than kept, because it was cooked
        from the model that has just been replaced.
        """
        first = not self.sceneLoaded
        self.sceneLoaded = True
        if self.capturing or not self.options.physics:
            return
        self.physicsPlatform = None
        if not self.enablePhysics(True) and first:
            sys.stdout.write("Physics: no walkable geometry; using free-fly.\n")
            sys.stdout.flush()

    # -- assembling the scene ---------------------------------------------
    def buildScenegraph(self, scene: Any) -> None:
        """(Re)build ``self.sg`` from a loaded scene.

        Safe to call again with another scene, which is how a catalogue browser
        swaps models.

        A scene with cameras of its own is shown **where it was authored**, since
        those camera poses are in its own space and re-centring would leave them
        pointing at nothing.  So is one the adapter says must not be moved -- a
        world, whose ground plane is at y=0.  Anything else is a model: centred
        and turned to :attr:`ViewerOptions.yaw` so it is seen from
        three-quarters on.
        """
        self.scene = scene
        self.radius = scene.radius or 1.0
        self._applyExposure(scene)
        self._cameraNames = [(camera.get('name') or 'camera')
                             for camera in scene.cameras]
        use_cameras = (not self.options.no_cameras) and bool(scene.viewpoints)

        children: List[Any] = []
        children.extend(self.backdropFor(scene))

        if use_cameras or not self.adapter.recentres:
            self.modelTransform = Transform(children=[scene.group])
            self._defaultModelRotation = (0, 1, 0, 0.0)
            children.append(self.modelTransform)
            if use_cameras:
                children.extend(scene.viewpoints)
                self.viewpoints = list(scene.viewpoints)
            else:
                self.viewpoints = []
        else:
            cx, cy, cz = scene.center
            centred = Transform(translation=(-cx, -cy, -cz), children=[scene.group])
            self._defaultModelRotation = (0, 1, 0, self.options.yaw)
            self.modelTransform = Transform(rotation=self._defaultModelRotation,
                                            children=[centred])
            children.append(self.modelTransform)
            self.viewpoints = []

        children.extend(self.lightsFor(scene))
        self.sg = SceneGraph(children=children)
        self.setupAnimation(scene)

        if use_cameras:
            sys.stdout.write("Found %d camera(s); PageUp/PageDown to cycle.\n"
                             % len(self.viewpoints))
            self.selectInitialCamera()
        else:
            self.frameModel(self.radius)
            self.reportStrays(scene)
        self.updateOverlay()

    @staticmethod
    def reportStrays(scene: Any) -> None:
        """Say when the fit ignored geometry the file left far outside the model.

        The camera is framed on the model rather than on everything the file
        draws (see
        :func:`~OpenGLContext.loaders.gltf.transforms.framing_bounds`), so a
        part stranded a hundred model-widths away is still rendered but starts
        off screen.  Saying so is the difference between a model that looks
        complete and one the user goes looking through for what is missing.
        """
        strays = getattr(scene, 'strays', 0)
        if strays:
            sys.stdout.write(
                "Framed on the model: %d part(s) of this file sit up to %.0f times "
                "its size away and start out of view.\n"
                % (strays, getattr(scene, 'stray_reach', 0.0)))

    def _applyExposure(self, scene: Any) -> None:
        """Publish the exposure and ambient the PBR pass reads off this context.

        The loader's light meter is for a **self-lit scene on black**, whose own
        punctual lights would otherwise clip.  Shown against an environment that
        environment is the key light instead, and the punctual-only reading is
        then badly wrong -- a lamp whose bulb sits at its own centre meters an
        absurd illuminance and crushes the scene to nothing -- so the metered
        stop-down applies only in the black-background case.

        glTF has no ambient term at all; it is zeroed so a self-lit scene reads
        dark with crisp lights rather than washed flat.
        """
        metered = float(getattr(scene, 'exposure', 1.0))
        self.gltf_exposure = metered if self.options.background == 'none' else 1.0
        self.gltf_scene_ambient = 0.0

    # -- the backdrop -----------------------------------------------------
    def backdropFor(self, scene: Any) -> List[Any]:
        """The ``Background`` to add, per :attr:`ViewerOptions.background`.

        Nothing, when the scene brought its own: a VRML world is authored
        complete, and a second ``Background`` beside its sky is not a second sky
        but a fight over which of the two is bound.  An explicit
        ``--background`` still wins, since asking for one is asking to replace
        whatever was there.
        """
        spec = self.options.background
        if spec is None and env.count_backgrounds(scene.group):
            return []
        backdrop = env.background_for(spec, sys.stderr.write)
        return [backdrop] if backdrop is not None else []

    # -- lighting ---------------------------------------------------------
    def lightsFor(self, scene: Any) -> List[Any]:
        """The lights to add, per :attr:`ViewerOptions.lights`.

        ``auto`` leaves a scene that lights itself alone and rigs one that does
        not, so nothing is ever shown in the dark and nothing authored is
        overridden.
        """
        mode = self.options.lights
        if mode == 'off':
            return []
        found = env.count_lights(scene.group)
        if mode == 'auto' and found:
            sys.stdout.write("Found %d light(s) in the file; using them.\n" % found)
            sys.stdout.flush()
            return []
        sys.stdout.write("Adding a default sun + fill rig.\n")
        sys.stdout.flush()
        return self.defaultLights(self.radius)

    @staticmethod
    def defaultLights(radius: float) -> List[Light]:
        """A low warm sun and a cool sky fill, sized to the model.

        One shadow-casting sun does the readable work -- low and well off to the
        side, so shadows are long and say something about the shape -- and the
        fill from the opposite side lifts them just enough to keep form in them.
        """
        return [
            DirectionalLight(direction=(-0.62, -0.42, -0.28),
                             color=(1.0, 0.86, 0.62), intensity=3.6,
                             castShadows=True),
            PointLight(location=(radius * 2, radius * 2.2, -radius * 2),
                       color=(0.55, 0.68, 0.92), intensity=0.25,
                       attenuation=(1, 0, 0), castShadows=False),
        ]

    # -- framing ----------------------------------------------------------
    def frameModel(self, radius: float) -> None:
        """Put the camera where the whole model can be seen.

        An explicit eye and target replace the fit entirely, which is how an
        interior shot -- standing inside a building looking along it -- is
        expressed, since no on-axis fit can say that.
        """
        eye, target = self.options.eye, self.options.look_at
        if eye is not None and target is not None:
            pose = framing.look_from(eye, target, radius)
        else:
            pose = framing.fit_sphere(radius, self.options.margin,
                                      self.options.elevation, self.options.tilt)
        if pose is None:
            return
        self.applyCameraPose(pose)

    def applyCameraPose(self, pose: framing.CameraPose) -> None:
        """Move the view platform to a computed pose."""
        self.platform.setFrustum(pose.fov, None, pose.near, pose.far)
        self.platform.setPosition(pose.position)
        if pose.quaternion is not None:
            self.platform.quaternion = pose.quaternion
        else:
            self.platform.setOrientation(pose.orientation)

    # -- the model's own cameras ------------------------------------------
    def resolveCamera(self, selector: str) -> Optional[int]:
        """Index of the camera named or numbered ``selector``, or None."""
        for i, name in enumerate(self._cameraNames):
            if name == selector:
                return i
        lowered = selector.lower()
        for i, name in enumerate(self._cameraNames):
            if name.lower() == lowered:
                return i
        if selector.lstrip('-').isdigit():
            index = int(selector)
            if 0 <= index < len(self.viewpoints):
                return index
        return None

    def selectInitialCamera(self) -> None:
        """Bind the camera the options asked for, if any."""
        selector = self.options.camera
        if not selector:
            return
        index = self.resolveCamera(selector)
        if index is None:
            sys.stderr.write("No camera matching %r; using the first.\n" % selector)
            return
        self.viewpoints[index].isBound = True
        self.cameraIndex = index

    def cycleViewpoint(self, delta: int) -> None:
        """Bind the next camera along, and take the avatar with you.

        In walk mode the avatar owns the camera, so it has to go to the chosen
        viewpoint too -- otherwise its pose snaps the view straight back.
        """
        if not self.viewpoints:
            return
        graph = self.getSceneGraph()
        current = getattr(graph, 'boundViewpoint', None) if graph else None
        try:
            index = self.viewpoints.index(current)
        except ValueError:
            index = self.cameraIndex
        following = (index + delta) % len(self.viewpoints)
        if current is not None:
            current.isBound = False
        self.viewpoints[following].isBound = True
        self.cameraIndex = following
        self.moveAvatarToViewpoint(self.viewpoints[following])
        self.updateOverlay()
        self.triggerRedraw(1)

    def nextCamera(self, event: Any = None) -> None:
        self.cycleViewpoint(1)

    def previousCamera(self, event: Any = None) -> None:
        self.cycleViewpoint(-1)

    # -- walking ----------------------------------------------------------
    def setupWalking(self) -> None:
        """Offer the walk/free-fly toggle for this model.

        A viewpoint that drops the avatar inside geometry is never a trap:
        ``g`` flies out and ``g`` again resumes walking from there.  Skipped for
        a capture, which wants one deterministic frame and not a simulation.
        """
        if self.capturing or getattr(self, 'sg', None) is None:
            self._freeManager = getattr(self, 'movementManager', None)
            return
        self.declareMovementModes()
        self.physicsYaw = self.options.yaw
        wanted = self.sceneLoaded and self.options.physics
        if not self.setupPhysics(enable=wanted) and wanted:
            sys.stdout.write("Physics: no walkable geometry; using free-fly.\n")
        sys.stdout.write("Press 'g' to toggle walk (physics) / free-fly.\n")
        sys.stdout.flush()

    def declareMovementModes(self) -> None:
        """Say what the ways of moving are, before anything has moved.

        The modes belong to the *viewer*, not to the avatar: the controls page
        offers what the context declares, and it used to find nothing because
        these were declared only as a side effect of building a physics world --
        so a viewer in free-fly, which is the default, had no controls page and
        nothing for ``m`` to cycle.

        At scale 1 to begin with; :meth:`applyMovementModes` redeclares them
        against the avatar's real size once a world has been cooked.  A host
        that declared its own vocabulary keeps it.
        """
        definition = getattr(self, 'contextDefinition', None)
        if definition is None or getattr(definition, 'movementModes', None):
            return
        from OpenGLContext.move.modes import walk_fly_modes
        definition.movementModes = walk_fly_modes(1.0)

    def cycleMovementMode(self, event: Any = None) -> Any:
        """Step to the next declared movement mode, as ``m`` does in twitch.

        The modes are declared nodes on the context definition, so the settings
        screen presents this viewer's navigation the same way it presents any
        other program's, and there is nothing to cycle until a scene has
        declared some.
        """
        navigation = self.getNavigation()
        mode = navigation.cycle() if navigation is not None else None
        if mode is not None:
            self.updateOverlay()
            self.triggerRedraw(1)
        return mode

    def physicsSpawnViewpoints(self) -> Sequence[Any]:
        """The model's own cameras, the selected one first.

        Authored cameras are curated open spots, which is what a spawn wants,
        and the selected one supplies the heading to start out facing.
        """
        if not self.viewpoints:
            return ()
        index = self.cameraIndex
        return list(self.viewpoints[index:]) + list(self.viewpoints[:index])

    def onPhysicsModeChanged(self) -> None:
        self.updateOverlay()

    # -- animation --------------------------------------------------------
    def setupAnimation(self, scene: Any) -> None:
        """Bind a player to the chosen animation of a freshly loaded scene."""
        self._animations = list(getattr(scene, 'animations', []) or [])
        self._animationNames = [animation.name or ('animation%d' % i)
                                for i, animation in enumerate(self._animations)]
        self._animationIndex = self.resolveAnimation(self.options.animation)
        self._animationClock = 0.0
        self._animationLast = None
        self._player = None
        # A pinned time is one deterministic pose, so it clamps rather than
        # loops: at exactly the duration it must show the end, not wrap to nothing.
        loop = self.options.anim_time is None
        if not (self._animations and self.options.animate):
            return
        self._player = scene.player(self._animationIndex, loop=loop)
        if self._player is None:
            return
        sys.stdout.write("Playing animation [%d/%d] %r (%.2fs).\n" % (
            self._animationIndex + 1, len(self._animations),
            self._animationNames[self._animationIndex], self._player.duration))
        sys.stdout.flush()
        self._player.evaluate(self.pinnedOr(0.0))   # show the first pose at once

    def resolveAnimation(self, selector: Any) -> int:
        """Index of the animation named or numbered ``selector`` (0 by default)."""
        if not self._animations or selector is None:
            return 0
        for i, name in enumerate(self._animationNames):
            if name == selector or name.lower() == str(selector).lower():
                return i
        if str(selector).lstrip('-').isdigit():
            return int(selector) % len(self._animations)
        sys.stderr.write("No animation matching %r; playing the first.\n" % selector)
        return 0

    def pinnedOr(self, t: float) -> float:
        """``t``, unless the options pin the animation to one time."""
        pinned = self.options.anim_time
        return pinned if pinned is not None else t

    def advanceAnimation(self) -> bool:
        """Advance the animation by wall time.  Returns whether to redraw."""
        if self._player is None:
            return False
        if self.options.anim_time is not None:
            self._player.evaluate(self.options.anim_time)
            return False            # a pinned pose is static; nothing to redraw for
        if not self._animationPlaying:
            return False
        now = self._now()
        if self._animationLast is not None:
            self._animationClock += min(now - self._animationLast,
                                        MAX_ANIMATION_STEP)
        self._animationLast = now
        self._player.evaluate(self._animationClock)
        return True

    def toggleAnimation(self, event: Any = None) -> None:
        self._animationPlaying = not self._animationPlaying
        self._animationLast = None      # do not count the time spent paused
        self.updateOverlay()
        self.triggerRedraw(1)

    def cycleAnimation(self, delta: int) -> None:
        """Play the next animation along, asking the scene for its player.

        **The scene builds it, not this.**  A player made here from the
        animation and the node transforms alone loses the skins and the
        world-matrix hook the scene wires in, so a skinned model -- Fox,
        CesiumMan, BrainStem -- froze in the pose it was last left in while the
        caption said the new animation was playing.
        """
        if not self._animations or self.scene is None:
            return
        self._animationIndex = (self._animationIndex + delta) % len(self._animations)
        self._player = self.scene.player(self._animationIndex, loop=True)
        self._animationClock = 0.0
        self._animationLast = None
        self.updateOverlay()
        self.triggerRedraw(1)

    def nextAnimation(self, event: Any = None) -> None:
        self.cycleAnimation(1)

    def previousAnimation(self, event: Any = None) -> None:
        self.cycleAnimation(-1)

    # -- turntable --------------------------------------------------------
    def toggleTurntable(self, event: Any = None) -> None:
        """Start or stop the slow spin.

        Stopping snaps back to the model's default facing, so a capture taken
        after one still matches a reference pose.
        """
        self.options.turntable = not self.options.turntable
        if self.options.turntable:
            self._turntableStart = self._now()
        elif self.modelTransform is not None:
            self.modelTransform.rotation = self._defaultModelRotation
        self.triggerRedraw(1)

    def advanceTurntable(self) -> bool:
        """Turn the model by wall time.  Returns whether to redraw."""
        if not self.options.turntable or self.modelTransform is None:
            return False
        base = self._defaultModelRotation[3]
        elapsed = self._now() - self._turntableStart
        self.modelTransform.rotation = (0, 1, 0, base + elapsed * TURNTABLE_RATE)
        return True

    # -- the caption ------------------------------------------------------
    def updateOverlay(self) -> None:
        """Recompose the caption: what is loaded, which camera, and how you move."""
        self.overlayText = "%s\n%s%s%s%s" % (
            os.path.basename(self.source or 'scene'), self._libraryLine(),
            self._cameraLine(), self._animationLine(), self._modeLine())

    def _cameraLine(self) -> str:
        if not self.viewpoints:
            return ''
        name = (self._cameraNames[self.cameraIndex]
                if self.cameraIndex < len(self._cameraNames) else 'camera')
        return "[%d/%d] %s   (PgUp/PgDn: cameras)\n" % (
            self.cameraIndex + 1, len(self.viewpoints), name)

    def _animationLine(self) -> str:
        if not self._animations:
            return ''
        name = (self._animationNames[self._animationIndex]
                if self._animationIndex < len(self._animationNames) else 'animation')
        state = 'playing' if self._animationPlaying else 'paused'
        extra = "  ([ ]: switch)" if len(self._animations) > 1 else ""
        return "anim [%d/%d] %s  (%s, k: pause)%s\n" % (
            self._animationIndex + 1, len(self._animations), name, state, extra)

    def _libraryLine(self) -> str:
        """Where in the shelf you are, when you got here from it."""
        entry = self.libraryEntry
        if entry is None:
            return ''
        shelf = self.viewerLibrary().inCategory(entry.category)
        names = [item.name for item in shelf]
        if entry.name not in names:
            return ''
        return "%s [%d/%d] %s   (Ctrl+PgUp/PgDn)\n" % (
            entry.category, names.index(entry.name) + 1, len(names), entry.name)

    def _modeLine(self) -> str:
        if self.physicsWalking:
            return "walk: arrows/WASD move, space jump, f fly   g: free-fly"
        return "free-fly: arrows move, right-drag examine   g: walk (physics)"

    #: Every key the viewer answers to.  PageUp/PageDown are the scene's own
    #: cameras -- inside one world that is what they mean -- and Ctrl with them
    #: steps the *shelf*, to the next model along in the list this one came from.
    viewerKeys: Tuple[KeyBinding, ...] = (
        KeyBinding('<pagedown>', 'nextCamera', 'Next camera in this scene'),
        KeyBinding('<pageup>', 'previousCamera', 'Previous camera in this scene'),
        KeyBinding('n', 'nextCamera', 'Next camera in this scene'),
        KeyBinding('p', 'previousCamera', 'Previous camera in this scene'),
        KeyBinding('<pagedown>', 'nextInLibrary', 'Next model in the library',
                   CONTROL),
        KeyBinding('<pageup>', 'previousInLibrary',
                   'Previous model in the library', CONTROL),
        KeyBinding('k', 'toggleAnimation', 'Play or pause the animation'),
        KeyBinding(']', 'nextAnimation', 'Next animation'),
        KeyBinding('[', 'previousAnimation', 'Previous animation'),
        KeyBinding('t', 'toggleTurntable', 'Turntable on or off'),
        KeyBinding('m', 'cycleMovementMode', 'Next navigation mode'),
    )

    # -- the frame --------------------------------------------------------
    def setupCallbacks(self) -> None:  # pragma: no cover - binds live event handlers
        super(SceneViewerMixin, self).setupCallbacks()       # type: ignore[misc]
        for binding in self.viewerKeys:
            self.addEventHandler('keyboard', name=binding.name,
                                 state=binding.state,
                                 modifiers=binding.modifiers,
                                 function=getattr(self, binding.method))

    def advanceStreaming(self) -> bool:
        """Give a source that is still arriving its say in this frame.

        A 3D Tiles dataset is larger than memory and pages itself in against
        wherever the camera now is; a file read once wants nothing here and says
        so by not overriding :meth:`SceneAdapter.update`.
        """
        return bool(self.adapter.update(self))

    def OnIdle(self, *args: Any) -> int:  # pragma: no cover - interactive idle loop
        # A finished background load is applied here, on the render thread,
        # before anything else looks at the scenegraph.
        if self.pollPendingScene():
            return 1
        streamed = self.advanceStreaming()
        animated = self.advanceAnimation()
        if self.capturing:
            # Keep drawing so the adaptive analytic-sky IBL converges, as it
            # does live, before the frame is taken.
            self.triggerRedraw(1)
        elif self.physicsWalking:
            self.stepPhysics()
        elif self.advanceTurntable() or animated or streamed:
            self.triggerRedraw(1)
        return 1

    def OnShutdown(self, *args: Any, **named: Any) -> Any:  # pragma: no cover - GL teardown
        """Let the adapter release what it is holding, then tear down.

        A streaming source owns worker threads and a tile cache; leaving them
        running past the window is how a viewer fails to exit.
        """
        self.adapter.shutdown()
        shutdown = getattr(super(SceneViewerMixin, self), 'OnShutdown', None)
        return shutdown(*args, **named) if shutdown is not None else None

    def SwapBuffers(self) -> Any:  # pragma: no cover - GL swap + capture
        # These read the back buffer, which holds the frame just drawn
        # only until it is swapped away.
        captured = self.tickCapture()
        self.takePendingScreenshot()
        result = super(SceneViewerMixin, self).SwapBuffers()  # type: ignore[misc]
        if captured:
            self.finishCapture()
        return result

    @staticmethod
    def _now() -> float:
        """Wall clock the animation and the turntable are advanced against."""
        from time import time
        return time()


class ViewerContext(OverlayMixin, SceneViewerMixin, _Base):
    """The viewing component over this platform's interactive context.

    ``OverlayMixin`` comes **first**, ahead of the navigation the base context
    brings, so a screen that is up takes the keys and the mouse instead of the
    avatar walking off while somebody reads the settings.
    """
